"""The adapter contract. One file per provider in this folder; each subclasses Provider.

Adding a provider = a new file with a class that sets the fields below and implements the slots it supports.
Every method saves its result to `out` and returns a Result. Costs are real (from the provider) when the
provider reports them, else an estimate, else None (unknown).

Paid jobs that run on the provider's side (createTask, a prediction, a request) are written down in
"<out>.job.json" as soon as the provider accepts them, and the file is deleted once the result is saved to
`out` (or the provider says the job failed or is gone). A run that times out, loses the connection or is
killed leaves the file behind, and calling the same method for the same `out` again collects that job
instead of paying for a new one.
"""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from http.client import HTTPException     # not `import http.client`: the http() below would shadow it

JOB = ".job.json"           # <out>.job.json = the paid job that will write `out`, until it's collected


class ProviderError(Exception):
    def __init__(self, msg, code=None, retry=False, rejected=False, made=False, cost=None):
        super().__init__(msg)
        self.code = code
        self.made = made                    # True = the job finished (and was paid) but its file wasn't saved
        self.cost = cost                    # with made: the USD it cost (real, else expected), or None
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

    def describe(self, slot, chars=None, model=None):
        """For a provider that bills in something other than dollars (e.g. plan characters): a free one-line
        note on what this job will use and what's left, else None."""
        return None

    # ---- paid jobs an earlier run started and didn't collect ----

    def pending(self, out):
        """The job an earlier run of this adapter left in <out>.job.json, else None:
        {"provider", "model", "id", "poll", "started", "usd", "note"}."""
        try:
            with open(out + JOB, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, ValueError, TypeError):
            return None
        return job if isinstance(job, dict) and job.get("provider") == self.name and job.get("id") else None

    def remember(self, out, model, job_id, poll, usd=None, note=None):
        """Call right after the provider accepted a paid job for `out`: until the result is saved, a re-run
        collects this job instead of starting (and paying for) another. usd = what this job is expected to
        cost, note = what it is (e.g. "model, 4s"): a re-run that collects it reports these, not its own."""
        if not out or not job_id:
            return
        job = {"provider": self.name, "model": model, "id": job_id, "poll": poll,
               "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "usd": usd}
        if note:
            job["note"] = note
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
            with open(out + JOB + ".tmp", "w", encoding="utf-8") as f:
                json.dump(job, f, indent=1)
            os.replace(out + JOB + ".tmp", out + JOB)
        except OSError:
            pass                # the job runs anyway; only a re-run's free pick-up is lost (errors name the id)

    def forget(self, out):
        """The result is saved, or the provider no longer has the job: nothing left to collect."""
        if out:
            try:
                os.remove(out + JOB)
            except OSError:
                pass

    def again(self, out, where):
        """What to do about a job that may still finish, for error messages."""
        if out and self.pending(out):
            return (f"run the same command again to collect it: {os.path.basename(out)}{JOB} keeps the job id, so "
                    f"no new one is paid for (or see {where})")
        return f"check {where} before running it again, so it isn't paid for twice"

    @staticmethod
    def earlier(job):
        """Added to a Result's note when it came from a job an earlier run started."""
        return f" (finished job {job['id']} started {job.get('started', 'earlier')})" if job else ""

    @staticmethod
    def bought(job, usd, note):
        """(cost, note) for a Result: a job an earlier run started keeps what that run asked for and expected
        to pay (its own settings, not this run's), else this run's estimate and note."""
        if not job:
            return usd, note
        return job.get("usd"), (job.get("note") or job.get("model") or note) + Provider.earlier(job)

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


def download(url, out, tries=4, cost=None):
    """Save a result. Retried, because by now the job is already paid for. If the provider has already deleted
    the file, the job for `out` can't be collected by a re-run either, so its <out>.job.json goes too.
    Errors carry made=True and cost (what the job cost, or None), so the spend can still be logged."""
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
            if gone:
                try:
                    os.remove(out + JOB)
                except OSError:
                    pass
                raise ProviderError(f"Made, but the download failed ({e}): the provider no longer has the file at "
                                    f"{url}, so it can't be collected. Running it again makes a new one (paid).",
                                    code=e.code, made=True, cost=cost)
            if attempt == tries - 1:
                raise ProviderError(f"Made, but the download failed ({e}). The file may still be at: {url} "
                                    f"(providers delete results after a while, so save it soon). Running the same "
                                    f"command again downloads it without paying again.", made=True, cost=cost)
            time.sleep(5 * (attempt + 1))
