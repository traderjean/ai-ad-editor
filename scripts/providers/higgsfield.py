"""Higgsfield: one key and one USD balance for many image and video models (Kling, Wan, Seedance, GPT Image...).

Pattern for every model: upload local refs (presigned URL) -> POST /<model id> -> poll status_url -> download.
Docs: https://docs.higgsfield.ai. A key is an ID plus a secret: HF_KEY="<id>:<secret>" (or HF_API_KEY + HF_API_SECRET).
Only finished generations are charged; failed and blocked (nsfw) ones are refunded. The API reports no cost and
has no balance call, so costs are estimates from Higgsfield's published price list (None where it shows none).
Results and uploads are deleted after ~7 days, so results are downloaded straight away.
The public API has no voice, music or lip-sync models: those slots stay on another provider (or the Higgsfield
MCP, see SKILL.md).
"""
import math
import mimetypes
import os
import time
import uuid

from ._base import OutOfCredit, Provider, ProviderError, Result, download, http, with_retries

API = "https://api.higgsfield.ai"
NO_TEXT = " No on-screen text, no captions, no subtitles."
UPLOAD_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "audio/wav", "video/mp4")

# Qwen Image 3 edits with 1-3 references (character sheet + product) and returns PNG; GPT Image 2.5 Flare takes up to 16.
IMAGE_MODELS = {"draft": "alibaba/qwen-image-3", "standard": "alibaba/qwen-image-3", "best": "marketing-studio/image/flare"}
IMAGE_RES = {"draft": "1k", "standard": "2k", "best": "2k"}
FLARE_QUALITY = {"draft": "low", "standard": "medium", "best": "high"}
IMAGE_EST = {("alibaba/qwen-image-3", "1k"): 0.04, ("alibaba/qwen-image-3", "2k"): 0.075,
             ("xai/grok-imagine-image-2.0", "1k"): 0.04, ("xai/grok-imagine-image-2.0", "2k"): 0.08}

# Start frame -> clip. Wan 3.0 has known per-second prices and an audio switch; Kling 3.0 Pro for the best tier.
VIDEO_MODELS = {"draft": "alibaba/wan-3.0/image-to-video", "standard": "alibaba/wan-3.0/image-to-video",
                "best": "kling-video/v3.0/pro/image-to-video"}
VIDEO_RES = {"draft": "720p", "standard": "1080p", "best": "1080p"}
VIDEO_RATE = {("alibaba/wan-3.0", "480p"): 0.02, ("alibaba/wan-3.0", "720p"): 0.04, ("alibaba/wan-3.0", "1080p"): 0.08}  # USD/s
# Allowed clip lengths: a tuple = fixed choices, a range = any whole number of seconds.
DURATIONS = {"kling-video/v2.5": (5, 10), "kling-video/v2.6": (5, 10), "lightricks/ltx-2.5": (6, 8, 10),
             "minimax/hailuo": (6, 10), "alibaba/wan-3.0": range(2, 31), "kling-video/v3.0": range(3, 16),
             "kling-video/v3.0-turbo": range(3, 16), "kling-video/v4.0": range(3, 31),
             "bytedance/seedance-2.0": range(4, 16), "bytedance/seedance-2.5": range(4, 31)}
SOUND_SWITCH = ("kling-video/v2.6", "kling-video/v3.0")     # Kling models with sound on/off (others: no switch)


def family(model):
    """'alibaba/wan-3.0/image-to-video' -> 'alibaba/wan-3.0' (the part that sets the inputs and the price)."""
    return "/".join(model.split("/")[:2])


def snap(model, seconds):
    """The shortest clip length the model allows that covers `seconds` (else its longest)."""
    allowed = DURATIONS.get(family(model))
    want = max(1, math.ceil(seconds - 1e-6))
    if not allowed:
        return want
    return next((d for d in allowed if d >= want), max(allowed))


class Higgsfield(Provider):
    name = "higgsfield"
    label = "Higgsfield (images, video)"
    env_key = "HF_KEY"
    signup = "https://console.higgsfield.ai"
    slots = ("image", "video")
    default_models = {"image": IMAGE_MODELS, "video": VIDEO_MODELS}

    # ---- set-up: the key is an ID and a secret ----

    def key(self):
        k = os.environ.get("HF_KEY")
        if not k and os.environ.get("HF_API_KEY") and os.environ.get("HF_API_SECRET"):
            k = f"{os.environ['HF_API_KEY']}:{os.environ['HF_API_SECRET']}"
        if not k:
            raise ProviderError('HF_KEY is not set. Add HF_KEY="<key id>:<secret>" (from console.higgsfield.ai, '
                                'API keys) to your shell profile, then open a new terminal.')
        return k

    def has_key(self):
        return bool(os.environ.get("HF_KEY") or (os.environ.get("HF_API_KEY") and os.environ.get("HF_API_SECRET")))

    # ---- low level ----

    def _req(self, method, url, body=None, headers=None, want="json"):
        h = {"Authorization": f"Key {self.key()}"}
        h.update(headers or {})
        try:
            return with_retries(lambda: http(method, url, headers=h, body=body, want=want))
        except ProviderError as e:
            if e.code == 403 and "api_key_" not in str(e):        # 403 = balance used up (expired keys say so)
                raise OutOfCredit(f"Higgsfield balance has run out. Top up at console.higgsfield.ai. ({e})", code=403)
            if e.code in (401, 403):
                raise ProviderError(f"Higgsfield refused the key: {e}. Check HF_KEY (id:secret) in your shell "
                                    f"profile and that the key isn't expired or disabled.", code=e.code)
            raise

    def upload(self, path):
        """Upload a local file; returns a public URL (Higgsfield deletes it within ~7 days)."""
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype == "image/jpg":
            ctype = "image/jpeg"
        if ctype not in UPLOAD_TYPES:
            raise ProviderError(f"Higgsfield can't take {os.path.basename(path)} ({ctype}). "
                                f"Use PNG, JPEG or WebP for images, WAV for audio, MP4 for video.")
        d = self._req("POST", f"{API}/files/generate-upload-url", {"content_type": ctype})
        with open(path, "rb") as f:
            data = f.read()
        # The presigned URL gets exactly the headers Higgsfield names, and never the API key.
        put = d.get("upload_headers") or {"Content-Type": ctype}
        with_retries(lambda: http("PUT", d["upload_url"], headers=put, raw=data, timeout=300, want="bytes"))
        return d["public_url"]

    def _run(self, model, inp, timeout=900):
        """Submit + poll. Returns the finished request JSON.

        Every submit carries an Idempotency-Key, so resending after a network error or a busy reply returns the
        same request instead of making (and charging) a second one."""
        idem = str(uuid.uuid4())
        sub = self._req("POST", f"{API}/{model}", inp, headers={"Idempotency-Key": idem})
        status_url = sub.get("status_url") or f"{API}/requests/{sub['request_id']}/status"
        t0, every = time.time(), 2.0
        while True:
            d = self._req("GET", status_url)
            state = d.get("status")
            if state == "completed":
                return d
            if state == "nsfw":
                raise ProviderError("Higgsfield blocked this as unsafe (not charged). Soften the prompt or the "
                                    "reference images (often a person + a medical or body detail) and retry.")
            if state in ("failed", "canceled"):
                raise ProviderError(f"Higgsfield request {state} (not charged): {d.get('error') or 'no reason given'}")
            if time.time() - t0 > timeout:
                raise ProviderError(f"Higgsfield request {sub.get('request_id')} still '{state}' after {timeout}s. "
                                    f"It may still finish: check console.higgsfield.ai before running it again.")
            time.sleep(every)
            every = min(every * 1.5, 10)

    # ---- contract ----

    def check(self):
        # A status call for a request that can't exist: 404 means the key was accepted. Nothing is made.
        try:
            self._req("GET", f"{API}/requests/00000000-0000-0000-0000-000000000000/status")
        except OutOfCredit:
            return "key OK, but the balance looks empty (top up at console.higgsfield.ai)"
        except ProviderError as e:
            if e.code != 404:
                raise
        return "key OK (the API shows no balance: see console.higgsfield.ai, Billing)"

    def estimate(self, slot, quality, seconds=None, model=None, audio=False, chars=None):
        m = self.model_for(slot, quality, model)
        if slot == "image":
            return IMAGE_EST.get((family(m) if m.startswith("alibaba/") else m, IMAGE_RES.get(quality, "2k")))
        if slot == "video":
            rate = VIDEO_RATE.get((family(m), VIDEO_RES.get(quality, "1080p")))
            return rate * snap(m, seconds or 8) if rate else None
        return None

    def image(self, prompt, out, refs=(), aspect="9:16", quality="standard", model=None):
        m = self.model_for("image", quality, model)
        urls = [self.upload(p) for p in refs]
        res = IMAGE_RES.get(quality, "2k")
        inp = {"prompt": prompt, "aspect_ratio": aspect}
        if family(m) == "alibaba/qwen-image-3":   # two endpoints: edit (1-3 refs) or text-to-image
            if len(urls) > 3:
                raise ProviderError(f"Qwen Image 3 takes up to 3 reference images (got {len(urls)}). "
                                    f"Use --quality best (up to 16) or fewer references.")
            m = "alibaba/qwen-image-3" + ("/edit" if urls else "/text-to-image")
            inp.update(resolution=res, prompt_extend=False, enable_thinking=False)   # keep the prompt as written
            if urls:
                inp["image_urls"] = urls
        elif m.startswith("marketing-studio/image"):
            inp.update(resolution=res, quality=FLARE_QUALITY.get(quality, "medium"), image_urls=urls)
            if m == "marketing-studio/image":
                inp["quality"] = {"max": "high", "xhigh": "high"}.get(inp["quality"], inp["quality"])
        elif m.startswith("xai/grok-imagine-image"):
            inp.update(resolution=res, quality="low" if quality == "draft" else "medium", image_urls=urls)
        elif urls:
            inp["image_urls"] = urls
        d = self._run(m, inp, timeout=600)
        imgs = d.get("images") or []
        if not imgs or not imgs[0].get("url"):
            raise ProviderError("Higgsfield returned no image")
        download(imgs[0]["url"], out)
        return Result([out], self.estimate("image", quality, model=model), m)

    def video(self, prompt, out, frame=None, seconds=8, aspect="9:16", quality="standard", audio=False, model=None):
        m = self.model_for("video", quality, model)
        if not frame:                             # no start frame: the text-to-video twin, which takes an aspect ratio
            m = m.replace("/image-to-video", "/text-to-video")
        fam, length = family(m), snap(m, seconds)
        inp = {"prompt": prompt + ("" if audio else NO_TEXT), "duration": length}
        if frame:
            inp["image_url"] = self.upload(frame)
        if fam.startswith("kling-video/"):
            if fam in SOUND_SWITCH:
                inp["sound"] = "on" if audio else "off"
            elif fam in ("kling-video/v3.0-turbo", "kling-video/v4.0"):
                inp["resolution"] = VIDEO_RES.get(quality, "1080p")
            if not frame or fam in ("kling-video/v2.5", "kling-video/v2.6"):
                inp["aspect_ratio"] = aspect
        else:                                     # Wan, Seedance, LTX, PixVerse: an audio switch and a resolution
            inp["generate_audio"] = bool(audio)
            inp["resolution"] = VIDEO_RES.get(quality, "1080p")
            if fam in ("alibaba/wan-3.0", "lightricks/ltx-2.5") or not frame:
                inp["aspect_ratio"] = aspect
            if fam == "alibaba/wan-3.0":
                inp["enable_thinking"] = False
        d = self._run(m, inp, timeout=1800)
        url = (d.get("video") or {}).get("url")
        if not url:
            raise ProviderError("Higgsfield returned no video")
        download(url, out)
        est = self.estimate("video", quality, seconds=length, model=model)
        return Result([out], est, f"{m}, {length}s")
