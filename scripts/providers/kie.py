"""Kie.ai: one key and one credit balance for many image and video models (Nano Banana, Veo 3.1, ...).

Pattern for every model: upload local refs -> createTask -> poll recordInfo -> download resultUrls.
Docs: https://docs.kie.ai. Errors can come back as HTTP 200 with a non-200 "code" in the body.
200 credits = $1. The real cost of each task is recordInfo.creditsConsumed.
Kie keeps outputs ~14 days and uploads ~24h, so results are downloaded straight away.
"""
import json
import mimetypes
import os
import time
import uuid

from ._base import OutOfCredit, Provider, ProviderError, Result, download, http, submit, with_retries

API = "https://api.kie.ai/api/v1"
UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"
USD_PER_CREDIT = 0.005
NO_AUDIO = " No dialogue, no speech, no music, no on-screen text, no captions, no subtitles."

VIDEO_MODELS = {"draft": "veo3_lite", "standard": "veo3_fast", "best": "veo3"}
VIDEO_EST = {"veo3_lite": 0.175, "veo3_fast": 0.325, "veo3": 1.225}          # USD per 8s clip, 1080p
IMAGE_MODELS = {"draft": "google/nano-banana", "standard": "nano-banana-2", "best": "nano-banana-pro"}
IMAGE_EST = {"google/nano-banana": 0.02, "nano-banana-2": 0.05, "nano-banana-pro": 0.09}
# Lip-sync an existing clip: lite = one person facing the camera (faster), basic = busier scenes.
LIPSYNC_MODES = {"draft": "lite", "standard": "lite", "best": "basic"}
# Photo + voiceover -> talking video.
AVATAR_MODELS = {"draft": "infinitalk/from-audio", "standard": "kling/ai-avatar-standard", "best": "kling/ai-avatar-pro"}


class Kie(Provider):
    name = "kie"
    label = "Kie.ai (images, video, voice, lip-sync)"
    env_key = "KIE_API_KEY"
    signup = "https://kie.ai"
    slots = ("image", "video", "lipsync", "voice", "music")
    default_models = {"image": IMAGE_MODELS, "video": VIDEO_MODELS, "lipsync": LIPSYNC_MODES, "avatar": AVATAR_MODELS}

    # ---- low level ----

    def _req(self, method, url, body=None, raw=None, headers=None, paid=False):
        """paid=True for a call that starts a paid task: it is only resent when Kie turned it away."""
        h = {"Authorization": f"Bearer {self.key()}"}
        h.update(headers or {})

        def once():
            d = http(method, url, headers=h, body=body, raw=raw)
            code = d.get("code")
            if code not in (200, None) and not d.get("success", False):
                msg = d.get("msg") or d
                if str(code) == "402":
                    raise OutOfCredit(f"Kie credits have run out. Top up at kie.ai/billing. ({msg})", code=402)
                # 429 / 455 / 503 = Kie is busy and turned the request away, so nothing was made.
                raise ProviderError(f"Kie {code}: {msg}", code=code, rejected=str(code) in ("429", "455", "503"))
            return d
        return (submit if paid else with_retries)(once)

    def credits(self):
        return float(self._req("GET", f"{API}/chat/credit").get("data") or 0)

    def upload(self, path):
        """Upload a local file; returns a public URL (deleted by Kie after ~24h)."""
        boundary = uuid.uuid4().hex
        fname = os.path.basename(path)
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        parts = []
        for k, v in (("uploadPath", "ai-ad-editor"), ("fileName", f"{uuid.uuid4().hex[:8]}_{fname}")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        with open(path, "rb") as f:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + f.read() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        d = self._req("POST", UPLOAD, raw=b"".join(parts),
                      headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        data = d.get("data") or {}
        return data.get("downloadUrl") or data.get("fileUrl")

    def _run(self, model, inp, timeout=900, every=8):
        """createTask + poll, made again only when the task failed because Kie was busy (failed tasks aren't
        charged). Returns (result_urls, usd or None)."""
        return with_retries(lambda: self._run_once(model, inp, timeout, every), tries=4, base_wait=30)

    def _run_once(self, model, inp, timeout, every):
        task = self._req("POST", f"{API}/jobs/createTask", {"model": model, "input": inp}, paid=True)["data"]["taskId"]
        t0 = time.time()
        while True:
            try:
                d = self._req("GET", f"{API}/jobs/recordInfo?taskId={task}")["data"]
            except ProviderError as e:
                # The task exists and may still finish (and be charged): never start a second one from here.
                raise ProviderError(f"Lost track of Kie task {task} ({e}). It may still finish: check the logs "
                                    f"at kie.ai before running it again.", code=e.code) from e
            state = d.get("state")
            if state == "success":
                res = d.get("resultJson") or "{}"
                res = json.loads(res) if isinstance(res, str) else res
                data = res.get("data")
                urls = (res.get("resultUrls") or (data.get("result_urls") if isinstance(data, dict) else None)
                        or [x.get("audio_url") for x in (data if isinstance(data, list) else []) if x.get("audio_url")])
                credits = float(d.get("creditsConsumed") or 0)
                return urls, (credits * USD_PER_CREDIT if credits else None)
            if state == "fail":
                # Kie doesn't charge failed tasks. Most failures here are safety filters.
                busy = str(d.get("failCode")) in ("500", "503") or "busy" in str(d.get("failMsg")).lower()
                hint = ""
                if "generate audio" in str(d.get("failMsg")).lower():
                    hint = (" FIX: reword the clip prompt: take out brand names and any words written on things, "
                            "and anything that sounds like talking (ask, say, tell).")
                raise ProviderError(f"Kie task failed ({d.get('failCode')}): {d.get('failMsg')}{hint}", retry=busy)
            if time.time() - t0 > timeout:
                raise ProviderError(f"Kie task {task} still '{state}' after {timeout}s", retry=False)
            time.sleep(every)

    # ---- contract ----

    def check(self):
        bal = self.credits()
        return f"key OK, balance {bal:.0f} credits (${bal * USD_PER_CREDIT:.2f})"

    def estimate(self, slot, quality, seconds=None, model=None, audio=False, chars=None):
        m = self.model_for(slot, quality, model)
        return {"video": VIDEO_EST, "image": IMAGE_EST}.get(slot, {}).get(m)

    def image(self, prompt, out, refs=(), aspect="9:16", quality="standard", model=None):
        m = est = self.model_for("image", quality, model)
        urls = [self.upload(p) for p in refs]
        inp = {"prompt": prompt, "output_format": "png"}
        if m.startswith("google/nano-banana"):       # the older model has a separate edit endpoint
            if urls:
                m = "google/nano-banana-edit"
                inp["image_urls"] = urls
            inp["image_size"] = aspect
        else:
            inp["image_input"] = urls
            inp["aspect_ratio"] = aspect
            inp["resolution"] = "2K"
        res, usd = self._run(m, inp, timeout=600, every=4)
        if not res:
            raise ProviderError("Kie returned no image")
        download(res[0], out)
        return Result([out], usd if usd is not None else IMAGE_EST.get(est), m)

    def video(self, prompt, out, frame=None, seconds=8, aspect="9:16", quality="standard", audio=False, model=None):
        m = self.model_for("video", quality, model)
        inp = {"prompt": prompt + ("" if audio else NO_AUDIO), "model": m, "aspect_ratio": aspect,
               "resolution": "1080p", "duration": 8, "enable_translation": False}
        if frame:
            inp["image_urls"] = [self.upload(frame)]
            inp["generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"   # one image = the start frame
        else:
            inp["generation_type"] = "TEXT_2_VIDEO"
        # Veo sometimes refuses with "unable to generate audio" even when we mute it later. Failed tasks
        # aren't charged, so try: as asked -> without the no-audio line -> the other Veo models that cost no
        # more than the one the user approved (never a dearer model behind their back).
        tries = [(m, inp["prompt"])]
        if not audio:
            tries.append((m, prompt))
        cap = VIDEO_EST.get(m, 0)
        tries += [(alt, prompt) for alt in ("veo3_lite", "veo3_fast", "veo3") if alt != m and VIDEO_EST[alt] <= cap]
        last = None
        for model_id, text in tries:
            try:
                res, usd = self._run("veo-3-1", dict(inp, model=model_id, prompt=text))
                break
            except ProviderError as e:
                if "generate audio" not in str(e).lower():
                    raise
                last = e
        else:
            raise last
        if not res:
            raise ProviderError("Kie returned no video")
        download(res[0], out)
        # Veo on Kie always makes 8s; the edit trims each clip to its shot length.
        note = model_id if model_id == m else f"{model_id} (after {m} refused audio)"
        return Result([out], usd if usd is not None else VIDEO_EST.get(model_id), note)

    def music(self, prompt, out, seconds=None, model=None):
        # Suno through Kie. Instrumental so it sits under a voiceover. Suno makes 2 takes; both are saved.
        inp = {"custom_mode": False, "instrumental": True, "model": model or "V6", "prompt": prompt[:500]}
        res, usd = self._run("ai-music-api/generate", inp, timeout=600)
        if not res:
            raise ProviderError("Kie returned no music")
        base, ext = os.path.splitext(out)
        files = []
        for i, url in enumerate(res[:2]):
            path = out if i == 0 else f"{base}_take2{ext or '.mp3'}"
            download(url, path)
            files.append(path)
        return Result(files, usd, f"suno {inp['model']}, {len(files)} take(s)")

    def voices(self):
        # Kie's ElevenLabs voices are a fixed list (the user's own ElevenLabs voices need a direct ElevenLabs key).
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kie_voices.json")) as f:
            return [(v["id"], v["name"], v["description"]) for v in json.load(f)]

    def voice(self, text, out, voice_id, model=None, settings=None):
        # ElevenLabs v3 through Kie: one line of "dialogue" with one voice. Supports [audio tags].
        if len(text) > 5000:
            raise ProviderError("Kie's voiceover takes up to 5,000 characters. Split the script into parts.")
        stab = (settings or {}).get("stability", 0.5)
        stab = min((0, 0.5, 1), key=lambda x: abs(x - stab))      # Kie accepts only 0, 0.5 or 1
        inp = {"dialogue": [{"text": text, "voice": voice_id}], "stability": stab}
        res, usd = self._run(model or "elevenlabs/text-to-dialogue-v3", inp, timeout=600, every=4)
        if not res:
            raise ProviderError("Kie returned no audio")
        download(res[0], out)
        return Result([out], usd, "elevenlabs v3 via kie")

    def lipsync(self, video, audio, out, quality="standard", model=None):
        # Output length follows the audio. The audio should be voice only (no music).
        mode = model or LIPSYNC_MODES[quality]
        inp = {"mode": mode, "video_url": self.upload(video), "audio_url": self.upload(audio)}
        if mode == "lite":
            inp["align_audio"] = True      # loop the clip if the line is longer than it
        res, usd = self._run("volcengine/video-to-video-lip-sync", inp)
        if not res:
            raise ProviderError("Kie returned no lip-synced video")
        download(res[0], out)
        return Result([out], usd, f"volcengine lip sync ({mode})")

    def avatar(self, image, audio, out, prompt="", quality="standard", model=None):
        m = model or AVATAR_MODELS[quality]
        inp = {"image_url": self.upload(image), "audio_url": self.upload(audio),
               "prompt": prompt or "The person talks naturally to the camera, small head movements, steady handheld phone shot."}
        if m.startswith("infinitalk"):
            inp["resolution"] = "720p"
        res, usd = self._run(m, inp, timeout=1800)
        if not res:
            raise ProviderError("Kie returned no talking video")
        download(res[0], out)
        return Result([out], usd, m)
