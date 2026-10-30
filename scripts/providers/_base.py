"""The adapter contract. One file per provider in this folder; each subclasses Provider.

Adding a provider = a new file with a class that sets the fields below and implements the slots it supports.
Every method saves its result to `out` and returns a Result. Costs are real (from the provider) when the
provider reports them, else an estimate, else None (unknown).
"""
import json
import os
import time
import urllib.error
import urllib.request
from http.client import HTTPException     # not `import http.client`: the http() below would shadow it


class ProviderError(Exception):
    def __init__(self, msg, code=None, retry=False, rejected=False):
        super().__init__(msg)
        self.code = code
        self.retry = retry or rejected      # True = busy / rate-limited, worth trying again
        self.rejected = rejected            # True = turned away before anything started (safe to resend a paid job)


class OutOfCredit(ProviderError):
    pass


class Result:
    def __init__(self, files, cost=None, note=""):
        self.files = files      # list of saved paths
        self.cost = cost        # USD or None
        self.note = note


class Provider:
    name = ""                   # used in providers.json and --provider
    label = ""                  # shown to the user
    env_key = ""                # environment variable that holds the API key
    signup = ""                 # where to get a key
    slots = ()                  # which of image / video / voice / music / lipsync it can fill
    default_models = {}         # slot -> {quality: model id}

    # ---- set-up ----

    def key(self):
        k = os.environ.get(self.env_key)
        if not k:
            raise ProviderError(f"{self.env_key} is not set. Add it to your shell profile, then open a new terminal.")
        return k

    def has_key(self):
        return bool(os.environ.get(self.env_key))

    def check(self):
        """Free call that proves the key works. Returns a one-line status (e.g. the balance)."""
        raise NotImplementedError

    def can(self, slot):
        """After check(): False if the key works but can't do this slot (e.g. no access to the video models)."""
        return slot in self.slots and slot not in getattr(self, "blocked", ())

    def model_for(self, slot, quality, override=None):
        if override:
            return override
        return self.default_models.get(slot, {}).get(quality)

    def estimate(self, slot, quality, seconds=None, model=None, audio=False, chars=None):
        """USD per item, or None if unknown. seconds = clip or audio length, chars = voiceover length."""
        return None

    # ---- slots (implement the ones listed in `slots`) ----

    def image(self, prompt, out, refs=(), aspect="9:16", quality="standard", model=None):
        raise NotImplementedError

    def video(self, prompt, out, frame=None, seconds=8, aspect="9:16", quality="standard", audio=False, model=None):
        raise NotImplementedError

    def voice(self, text, out, voice_id, model=None, settings=None):
        raise NotImplementedError

    def voices(self):
        """List of (voice_id, name, description) the user can pick from. Free."""
        raise NotImplementedError

    def music(self, prompt, out, seconds=None, model=None):
        raise NotImplementedError

    def lipsync(self, video, audio, out, quality="standard", model=None):
        """Re-time the mouth in an existing clip to a new voiceover; the clip's movement is kept."""
        raise NotImplementedError

    def avatar(self, image, audio, out, prompt="", quality="standard", model=None):
        """Turn one photo + a voiceover into a talking video (talking-head ads)."""
        raise NotImplementedError


# ---- small HTTP helpers shared by adapters (stdlib only, so nothing extra to install) ----

def http(method, url, headers=None, body=None, raw=None, timeout=120, want="json"):
    h = dict(headers or {})
    if body is not None:
        raw = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=raw, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:500]
        if e.code == 402:
            raise OutOfCredit(f"Out of credit ({e.code}): {msg}", code=402)
        raise ProviderError(f"HTTP {e.code}: {msg}", code=e.code, retry=e.code in (500, 502, 503, 504),
                            rejected=e.code == 429)
    except urllib.error.URLError as e:
        raise ProviderError(f"Network error: {e.reason}", retry=True)
    except (ConnectionError, TimeoutError, OSError, HTTPException) as e:   # e.g. "connection reset by peer", a cut-off reply
        raise ProviderError(f"Network error: {e}", retry=True)
    if want != "json":
        return data
    if not data.strip():
        return {}                                            # e.g. 202/204 with no body
    try:
        return json.loads(data)
    except ValueError:                                       # an HTML error page from a proxy, a cut-off reply
        raise ProviderError(f"Expected JSON from {url}, got: {data[:200]!r}", retry=True)


def with_retries(fn, tries=5, base_wait=10):
    """Run fn(); on a retryable error wait and try again. Only for calls that are safe to repeat
    (status checks, uploads). A call that starts a paid job goes through submit() instead."""
    for attempt in range(tries):
        try:
            return fn()
        except ProviderError as e:
            if not e.retry or attempt == tries - 1:
                raise
            time.sleep(base_wait * (attempt + 1))


def submit(fn, tries=5, base_wait=10):
    """Run fn(), a call that starts a paid job. Retried only when the provider turned it away (rate limit,
    busy): nothing was made. After a network error or a server error the job may already exist and be
    billing, so it stops and says so instead of paying twice."""
    for attempt in range(tries):
        try:
            return fn()
        except ProviderError as e:
            if e.rejected and attempt < tries - 1:
                time.sleep(base_wait * (attempt + 1))
                continue
            if e.retry and not e.rejected:
                raise ProviderError(f"{e}. The job may have started anyway: check the provider's dashboard "
                                    f"before running it again, so it isn't paid for twice.", code=e.code) from e
            raise


def download(url, out, tries=4):
    """Save a result. Retried, because by now the job is already paid for."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                data = r.read()
            with open(out, "wb") as f:
                f.write(data)
            return out
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, HTTPException) as e:
            gone = isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404, 410)   # retrying won't help
            if gone or attempt == tries - 1:
                raise ProviderError(f"Made, but the download failed ({e}). The file may still be at: {url} "
                                    f"(providers delete results after a while, so save it soon)")
            time.sleep(5 * (attempt + 1))
