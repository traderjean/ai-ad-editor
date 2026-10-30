"""Replicate: one token for many image, video, voice, music and lip-sync models, paid per output.

Pattern for every model: upload local files (data URL when small, else POST /v1/files) -> create a prediction
on the official model (POST /v1/models/{owner}/{name}/predictions) -> poll urls.get -> download the output.
Docs: https://replicate.com/docs/reference/http. Predictions report no cost, so costs come from each model's
published price (replicate.com/<owner>/<name>, checked 2026-10-30). Failed runs aren't charged.
Replicate deletes API inputs and outputs after an hour, so results are downloaded straight away.
A community model can be pinned with its version: --model owner/name:<version id>.
"""
import base64
import json
import math
import mimetypes
import os
import time
import uuid

from ._base import Provider, ProviderError, Result, download, http, submit, with_retries

API = "https://api.replicate.com/v1"
DATA_URL_MAX = 256 * 1024       # files up to this size go inline as data: URLs (Replicate's advice); bigger ones are uploaded
NO_TEXT = " No on-screen text, no captions, no subtitles."
NO_SPEECH = " No dialogue, no speech, no music."
DONE = ("succeeded", "failed", "canceled", "aborted")
SAFETY_WORDS = ("sensitive", "safety", "nsfw", "flagged", "policy", "moderation", "e005")

# ---- images: every tier takes up to 14 references (character sheet + product) and an explicit aspect ratio ----
IMAGE_MODELS = {"draft": "google/nano-banana-2.1", "standard": "google/nano-banana-2.1", "best": "google/nano-banana-pro"}
IMAGE_RES = {"draft": "1K", "standard": "2K", "best": "2K"}
# USD per image: a number, or {resolution: price}.
IMAGE_PRICE = {
    "google/nano-banana-2.1": {"1K": 0.0336, "2K": 0.0504, "4K": 0.1134},
    "google/nano-banana-pro": {"1K": 0.15, "2K": 0.15, "4K": 0.30},
    "google/nano-banana-2": {"1K": 0.067, "2K": 0.101, "4K": 0.151},
    "google/nano-banana-2-lite": 0.034,
    "google/nano-banana": 0.039,
    "bytedance/seedream-5-pro": {"1K": 0.045, "2K": 0.09},
    "bytedance/seedream-5-lite": 0.035,
    "bytedance/seedream-4.5": 0.04,
}
WITH_RESOLUTION = ("google/nano-banana-2", "google/nano-banana-2.1", "google/nano-banana-pro")

# ---- video: start frame -> clip, sound off unless it's a talking shot. Billed per second of output ----
VIDEO_MODELS = {"draft": "bytedance/seedance-1-pro-fast", "standard": "google/veo-3.1-fast", "best": "google/veo-3.1"}
TALKING_MODEL = "google/veo-3.1-fast"      # used for talking shots when the chosen model can't make sound
# USD per second: {"silent": .., "audio": ..} (None = can't), optionally per resolution.
VIDEO_PRICE = {
    "bytedance/seedance-1-pro-fast": {"silent": {"480p": 0.015, "720p": 0.025, "1080p": 0.06}, "audio": None},
    "google/veo-3.1-fast": {"silent": 0.10, "audio": 0.15},
    "google/veo-3.1": {"silent": 0.20, "audio": 0.40},
    "google/veo-3.1-lite": {"silent": None, "audio": {"720p": 0.05, "1080p": 0.08}},     # sound is always on
    "kwaivgi/kling-v3-video": {"silent": 0.224, "audio": 0.336},                         # mode pro (1080p)
    "kwaivgi/kling-v2.6": {"silent": 0.07, "audio": 0.14},
}
DURATIONS = {"google/veo-3.1-fast": (4, 6, 8), "google/veo-3.1": (4, 6, 8), "google/veo-3.1-lite": (4, 6, 8),
             "bytedance/seedance-1-pro-fast": range(2, 13), "bytedance/seedance-1.5-pro": range(2, 13),
             "kwaivgi/kling-v3-video": range(3, 16), "kwaivgi/kling-v2.6": (5, 10)}


# ---- voice: ElevenLabs on Replicate (a fixed list of 26 named voices, shared by every tier). USD per 1,000 characters ----
VOICE_MODELS = {"draft": "elevenlabs/turbo-v2.5", "standard": "elevenlabs/v3", "best": "elevenlabs/v3"}
VOICE_PRICE = {"elevenlabs/v3": 0.10, "elevenlabs/turbo-v2.5": 0.05, "elevenlabs/flash-v2.5": 0.05}

# ---- music: instrumental beds with an exact length ----
MUSIC_MODELS = {"draft": "stability-ai/stable-audio-2.5", "standard": "elevenlabs/music", "best": "elevenlabs/music"}
MUSIC_SECONDS = 60                        # when no length is given
MUSIC_FLAT = {"stability-ai/stable-audio-2.5": 0.20}          # USD per track
MUSIC_PER_SECOND = {"elevenlabs/music": 0.0083}               # USD per second of music


# ---- lip-sync (existing clip + a line of voiceover) and avatar (photo + voiceover). Output = audio length ----
LIPSYNC_MODELS = {"draft": "pixverse/lipsync", "standard": "sync/lipsync-2", "best": "sync/lipsync-2-pro"}
AVATAR_MODELS = {"draft": "prunaai/p-video-2-pro-avatar", "standard": "kwaivgi/kling-avatar-v2",
                 "best": "kwaivgi/kling-avatar-v2"}
KLING_AVATAR_MODE = {"draft": "std", "standard": "std", "best": "pro"}
# USD per second of output video.
LIPSYNC_PRICE = {"pixverse/lipsync": 0.04, "sync/lipsync-2": 0.05, "sync/lipsync-2-pro": 0.08325,
                 "heygen/lipsync-speed": 0.0333, "heygen/lipsync-precision": 0.0667}
AVATAR_PRICE = {"prunaai/p-video-2-pro-avatar": 0.04, "bytedance/omni-human-1.5": 0.16,
                ("kwaivgi/kling-avatar-v2", "std"): 0.056, ("kwaivgi/kling-avatar-v2", "pro"): 0.11}
TALK_PROMPT = "The person talks naturally to the camera, small head movements, steady handheld phone shot."


def snap(model, seconds):
    """The shortest clip length the model allows that covers `seconds` (else its longest)."""
    allowed = DURATIONS.get(model.split(":")[0])
    want = max(1, math.ceil(seconds - 1e-6))
    if not allowed:
        return want
    return next((d for d in allowed if d >= want), max(allowed))


def pick(price, res):
    return price.get(res) if isinstance(price, dict) else price


class Replicate(Provider):
    name = "replicate"
    label = "Replicate (images, video, voice, music, lip-sync)"
    env_key = "REPLICATE_API_TOKEN"
    signup = "https://replicate.com/account/api-tokens"
    slots = ("image", "video", "voice", "music", "lipsync")
    default_models = {"image": IMAGE_MODELS, "video": VIDEO_MODELS, "voice": VOICE_MODELS, "music": MUSIC_MODELS,
                      "lipsync": LIPSYNC_MODELS, "avatar": AVATAR_MODELS}

    # ---- low level ----

    def _h(self):
        return {"Authorization": f"Bearer {self.key()}"}

    def upload(self, path):
        """A URL Replicate can read: a data URL for small files, else an upload (kept by Replicate ~1 hour)."""
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        if len(data) <= DATA_URL_MAX:
            return f"data:{ctype};base64,{base64.b64encode(data).decode()}"
        boundary = uuid.uuid4().hex
        fname = os.path.basename(path).replace('"', "")
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="{fname}"\r\n'
                f'Content-Type: {ctype}\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
        h = dict(self._h(), **{"Content-Type": f"multipart/form-data; boundary={boundary}"})
        d = with_retries(lambda: http("POST", f"{API}/files", headers=h, raw=body, timeout=300))
        return d["urls"]["get"]

    def _run(self, model, inp, timeout=900, every=3):
        """Create one prediction and poll it to the end. Returns (output URLs, prediction).

        The create call is only resent when Replicate turned it away (rate limit); after a network error the
        prediction may exist, so it stops instead of paying twice. Polling never starts a new one."""
        if ":" in model:                       # owner/name:version = a community model pinned to a version
            url, body = f"{API}/predictions", {"version": model, "input": inp}
        else:
            url, body = f"{API}/models/{model}/predictions", {"input": inp}
        p = submit(lambda: http("POST", url, headers=self._h(), body=body))
        pid = p.get("id", "?")
        where = (p.get("urls") or {}).get("web") or f"https://replicate.com/p/{pid}"
        get = (p.get("urls") or {}).get("get") or f"{API}/predictions/{pid}"
        t0 = time.time()
        while p.get("status") not in DONE:
            if time.time() - t0 > timeout:
                raise ProviderError(f"Replicate prediction {pid} still '{p.get('status')}' after {timeout}s. It may "
                                    f"still finish (and be charged): see {where} before running it again.")
            time.sleep(every)
            try:
                p = with_retries(lambda: http("GET", get, headers=self._h()))
            except ProviderError as e:
                raise ProviderError(f"Lost track of Replicate prediction {pid} ({e}). It may still finish: "
                                    f"see {where} before running it again.", code=e.code) from e
        if p["status"] == "succeeded":
            urls = self._urls(p.get("output"))
            if not urls:
                raise ProviderError(f"Replicate {model} finished but returned no file ({where})")
            return urls, p
        err = str(p.get("error") or "no reason given")
        if p["status"] == "failed":
            hint = ""
            if any(w in err.lower() for w in SAFETY_WORDS):
                hint = (" FIX: it was blocked as unsafe. Soften the prompt or the reference images (often a person "
                        "+ a medical or body detail, or a brand name) and retry.")
            raise ProviderError(f"Replicate {model} failed (not charged): {err}{hint}")
        raise ProviderError(f"Replicate {model} was {p['status']}: {err}")

    @staticmethod
    def _urls(output):
        """Model outputs come as one URL, a list of URLs, or an object holding URLs."""
        if isinstance(output, str):
            return [output]
        if isinstance(output, list):
            return [u for o in output for u in Replicate._urls(o)]
        if isinstance(output, dict):
            return [u for o in output.values() for u in Replicate._urls(o)]
        return []

    # ---- contract ----

    def check(self):
        d = http("GET", f"{API}/account", headers=self._h())
        return f"key OK, account {d.get('username', '?')} (the API shows no balance: see replicate.com/account/billing)"

    def estimate(self, slot, quality, seconds=None, model=None, audio=False, chars=None):
        m = self.model_for(slot, quality, model) or ""
        if slot == "image":
            return pick(IMAGE_PRICE.get(m), IMAGE_RES.get(quality, "2K")) if m in IMAGE_PRICE else None
        if slot == "video":
            m = self._video_model(m, audio)
            length = snap(m, seconds or 8)
            rate = (VIDEO_PRICE.get(m) or {}).get("audio" if audio or m == "google/veo-3.1-lite" else "silent")
            rate = pick(rate, self._video_res(m, length)) if rate else None
            return rate * length if rate else None
        if slot == "voice":
            return VOICE_PRICE[m] * chars / 1000 if m in VOICE_PRICE and chars else None
        if slot == "music":
            if m in MUSIC_FLAT:
                return MUSIC_FLAT[m]
            return MUSIC_PER_SECOND[m] * self._music_seconds(m, seconds) if m in MUSIC_PER_SECOND else None
        if slot == "lipsync":
            return LIPSYNC_PRICE[m] * seconds if m in LIPSYNC_PRICE and seconds else None
        if slot == "avatar":
            rate = AVATAR_PRICE.get((m, KLING_AVATAR_MODE.get(quality, "std")) if m == "kwaivgi/kling-avatar-v2" else m)
            return rate * seconds if rate and seconds else None
        return None

    def image(self, prompt, out, refs=(), aspect="9:16", quality="standard", model=None):
        m = self.model_for("image", quality, model)
        urls = [self.upload(p) for p in refs]
        res = IMAGE_RES.get(quality, "2K")
        inp = {"prompt": prompt, "aspect_ratio": aspect}
        if m.startswith("google/nano-banana"):
            inp.update(image_input=urls, output_format="png")    # defaults are jpg and "match the first reference"
            if m in WITH_RESOLUTION:
                inp["resolution"] = res
            if m == "google/nano-banana-pro":
                inp["allow_fallback_model"] = False                # the fallback is another model: faces would drift
        elif m.startswith("bytedance/seedream"):
            if urls:
                inp["image_input"] = urls
            if m != "bytedance/seedream-4.5":
                inp["output_format"] = "png"
            if m == "bytedance/seedream-5-pro":
                inp["size"] = "1K" if res == "1K" else "2K"
            if m in ("bytedance/seedream-5-lite", "bytedance/seedream-4.5"):
                inp.update(sequential_image_generation="disabled", max_images=1)   # else it may make (and bill) several
        elif m.startswith("black-forest-labs/flux-2"):
            inp.update(input_images=urls, output_format="png")
        elif urls:
            inp["image_input"] = urls
        res_urls, _ = self._run(m, inp, timeout=600, every=2)
        download(res_urls[0], out)
        return Result([out], self.estimate("image", quality, model=model), m)

    # video helpers: talking shots need a model that can make sound; Veo Lite at 1080p must be 8s

    def _video_model(self, m, audio):
        if audio and (VIDEO_PRICE.get(m) or {}).get("audio", 0) is None:
            return TALKING_MODEL
        return m

    @staticmethod
    def _video_res(m, length):
        if m == "google/veo-3.1-lite":
            return "1080p" if length == 8 else "720p"
        return "1080p"

    def video(self, prompt, out, frame=None, seconds=8, aspect="9:16", quality="standard", audio=False, model=None):
        asked = self.model_for("video", quality, model)
        m = self._video_model(asked, audio)
        length = snap(m, seconds)
        frame_url = self.upload(frame) if frame else None
        base = m.split(":")[0]
        inp = {"prompt": prompt + ("" if audio else NO_TEXT), "duration": length, "aspect_ratio": aspect}
        if base.startswith("google/veo-3.1"):
            inp["resolution"] = self._video_res(base, length)
            if base == "google/veo-3.1-lite":
                if not audio:                   # Lite always makes sound: ask for none (the edit mutes it anyway)
                    inp["prompt"] += NO_SPEECH
            else:
                inp["generate_audio"] = bool(audio)
            if frame_url:
                inp["image"] = frame_url
        elif base.startswith("kwaivgi/kling"):
            inp["generate_audio"] = bool(audio)
            if base == "kwaivgi/kling-v3-video":
                inp["mode"] = "pro"
            if frame_url:
                inp["start_image"] = frame_url
        elif base.startswith("bytedance/seedance"):
            if base == "bytedance/seedance-1-pro-fast":
                inp["resolution"] = "1080p"
            else:
                inp["generate_audio"] = bool(audio)
            if frame_url:
                inp["image"] = frame_url
        elif frame_url:
            inp["image"] = frame_url
        urls, _ = self._run(m, inp, timeout=1800, every=5)
        download(urls[0], out)
        note = f"{m}, {length}s" + ("" if m == asked else f" (talking shot: {asked} makes no sound)")
        return Result([out], self.estimate("video", quality, seconds=length, model=model, audio=audio), note)

    def voices(self):
        # The ElevenLabs models on Replicate take a voice name from a fixed list (not the user's own ElevenLabs
        # voices: those need a direct ElevenLabs key).
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "replicate_voices.json")) as f:
            return [(v["id"], v["name"], v["description"]) for v in json.load(f)]

    def voice(self, text, out, voice_id, model=None, settings=None):
        m = model or VOICE_MODELS["standard"]
        if len(text) > 5000:
            raise ProviderError("ElevenLabs takes up to 5,000 characters per voiceover. Split the script into parts.")
        s = {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}
        s.update(settings or {})
        inp = {"prompt": text, "voice": voice_id, "similarity_boost": s["similarity_boost"],
               "speed": min(max(s["speed"], 0.7), 1.2)}                  # Replicate refuses speeds outside 0.7-1.2
        inp["stability"] = min((0, 0.5, 1), key=lambda x: abs(x - s["stability"])) if m == "elevenlabs/v3" else s["stability"]
        if s.get("style") is not None:
            inp["style"] = s["style"]
        if s.get("language"):
            inp["language_code"] = s["language"]                          # Replicate's default is "en"
        urls, _ = self._run(m, inp, timeout=600, every=2)
        download(urls[0], out)
        return Result([out], self.estimate("voice", "standard", model=m, chars=len(text)), m)

    @staticmethod
    def _music_seconds(m, seconds):
        sec = int(round(seconds or MUSIC_SECONDS))
        if m == "elevenlabs/music":
            return min(max(sec, 5), 300)
        if m == "stability-ai/stable-audio-2.5":
            return min(max(sec, 1), 190)
        return sec

    def music(self, prompt, out, seconds=None, model=None):
        m = model or MUSIC_MODELS["standard"]
        sec = self._music_seconds(m, seconds)
        text = prompt.rstrip(". ") + ". Instrumental, no vocals."
        if m == "elevenlabs/music":
            inp = {"prompt": text, "music_length_ms": sec * 1000, "force_instrumental": True,
                   "output_format": "mp3_high_quality"}
        else:                                 # Stable Audio 2.5 (and most others) take a length in seconds
            inp = {"prompt": text, "duration": sec}
        urls, _ = self._run(m, inp, timeout=900, every=4)
        download(urls[0], out)
        return Result([out], self.estimate("music", "standard", seconds=sec, model=m), f"{m}, {sec}s")

    def lipsync(self, video, audio, out, quality="standard", model=None):
        # The output is as long as the line: a longer clip is trimmed, a shorter one plays back and forth.
        m = self.model_for("lipsync", quality, model)
        inp = {"video": self.upload(video), "audio": self.upload(audio)}
        if m.startswith("sync/"):
            inp.update(sync_mode="bounce", temperature=0.5, active_speaker=False)
        elif m.startswith("heygen/"):
            inp["enable_dynamic_duration"] = True
        urls, _ = self._run(m, inp, timeout=1800, every=5)
        download(urls[0], out)
        return Result([out], self.estimate("lipsync", quality, seconds=self._seconds(audio), model=model), m)

    def avatar(self, image, audio, out, prompt="", quality="standard", model=None):
        m = self.model_for("avatar", quality, model)
        talk = self._seconds(audio)
        if m == "bytedance/omni-human-1.5" and talk >= 35:
            raise ProviderError(f"OmniHuman 1.5 takes under 35 seconds of audio (this is {talk:.0f}s). "
                                f"Use the default avatar model, or split the voiceover at a pause.")
        if m == "kwaivgi/kling-avatar-v2" and os.path.getsize(audio) > 5 * 1024 * 1024:
            audio = self._small_mp3(audio, out)            # Kling Avatar takes audio files up to 5MB
        inp = {"image": self.upload(image), "audio": self.upload(audio), "prompt": prompt or TALK_PROMPT}
        if m == "kwaivgi/kling-avatar-v2":
            inp["mode"] = KLING_AVATAR_MODE.get(quality, "std")
        elif m == "prunaai/p-video-2-pro-avatar":
            inp.update(resolution="768p", prompt_upsampling=False)   # keep the prompt as written
        urls, _ = self._run(m, inp, timeout=3600, every=10)
        download(urls[0], out)
        return Result([out], self.estimate("avatar", quality, seconds=talk, model=model), m)

    @staticmethod
    def _seconds(path):
        from common import duration                       # scripts/ is on the path when run via generate.py
        return duration(path)

    @staticmethod
    def _small_mp3(audio, out):
        from common import run_ffmpeg
        small = os.path.splitext(out)[0] + "_audio.mp3"
        run_ffmpeg(["-i", audio, "-vn", "-ac", "1", "-b:a", "128k", small])
        return small
