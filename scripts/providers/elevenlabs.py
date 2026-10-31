"""ElevenLabs: voiceovers. Default model eleven_v3 (most natural, supports [audio tags]).

Billed in characters from the user's monthly plan, not dollars. Text to speech answers with the audio itself, so
there is no job to pick up later (no <out>.job.json)."""
import re
import urllib.parse

from ._base import OutOfCredit, Provider, ProviderError, Result, http, submit

API = "https://api.elevenlabs.io"


class ElevenLabs(Provider):
    name = "elevenlabs"
    label = "ElevenLabs (voiceover)"
    env_key = "ELEVENLABS_API_KEY"
    signup = "https://elevenlabs.io"
    slots = ("voice",)
    default_models = {"voice": {"draft": "eleven_flash_v2_5", "standard": "eleven_v3", "best": "eleven_v3"}}

    def _h(self):
        return {"xi-api-key": self.key()}

    def _req(self, method, url, **kw):
        """http() with ElevenLabs' two 401s told apart: plan characters used up vs a refused key."""
        try:
            return http(method, url, headers=self._h(), **kw)
        except ProviderError as e:
            msg = str(e)
            if e.code == 401 and "quota_exceeded" in msg:
                n = re.search(r"([\d,]+) credits remaining, while ([\d,]+) credits are required", msg)
                have = f" ({n.group(1)} left, {n.group(2)} needed)" if n else ""
                raise OutOfCredit(f"ElevenLabs characters for this month are used up{have}. Top up or upgrade at "
                                  f"elevenlabs.io, shorten the script, or run again with --provider kie.", code=401) from e
            if e.code == 401 and "invalid_api_key" in msg:
                raise ProviderError("ELEVENLABS_API_KEY was refused (invalid or revoked): make a new key at "
                                    "elevenlabs.io (Developers, API keys), put it in your shell profile and open a "
                                    "new terminal.", code=401) from e
            raise

    def check(self):
        # Restricted keys often lack user_read, so fall back to the voice list, then report what's missing.
        try:
            d = self._req("GET", f"{API}/v1/user/subscription")
            used, limit = d.get("character_count", 0), d.get("character_limit", 0)
            return f"key OK, {d.get('tier', '?')} plan, {limit - used:,} characters left this month"
        except ProviderError as e:
            if e.code != 401 or "permission" not in str(e).lower():     # a bad or revoked key is a 401 too
                raise
        try:
            return f"key OK, {len(self.voices())} voices available (restricted key: no plan info)"
        except ProviderError as e:
            if e.code != 401 or "permission" not in str(e).lower():
                raise
        return "key set, but restricted: can't list voices for free. Text to speech may still work; pass --voice <id>"

    def describe(self, slot, chars=None, model=None):
        """Plan characters this voiceover will use and what's left (a free call), or None when the key can't
        read the plan. The Flash and Turbo models use half a character per character on most plans."""
        if slot != "voice" or not chars:
            return None
        try:
            d = self._req("GET", f"{API}/v1/user/subscription")
        except ProviderError:
            return None
        left = d.get("character_limit", 0) - d.get("character_count", 0)
        need = chars // 2 if any(w in (model or "") for w in ("flash", "turbo")) else chars
        short = (": NOT ENOUGH, top up at elevenlabs.io, shorten the script, or use --provider kie"
                 if need > left else "")
        return f"billed in plan characters: about {need:,} of the {left:,} left this month{short}"

    def voices(self):
        d = self._req("GET", f"{API}/v1/voices")
        out = []
        for v in d.get("voices", []):
            labels = v.get("labels") or {}
            desc = ", ".join(x for x in (labels.get("gender"), labels.get("age"), labels.get("accent"),
                                         labels.get("descriptive") or labels.get("description"),
                                         labels.get("use_case") or labels.get("use case")) if x)
            out.append((v["voice_id"], v.get("name", ""), desc))
        return out

    def voice(self, text, out, voice_id, model=None, settings=None):
        s = {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}
        s.update(settings or {})
        language = s.pop("language", None)
        body = {"text": text, "model_id": model or "eleven_v3", "voice_settings": s}
        if language and "v2_5" in body["model_id"]:      # only the v2.5 models take a forced language; v3 detects it
            body["language_code"] = language
        url = f"{API}/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=mp3_44100_128"
        # Paid: resent only when ElevenLabs turned it away (429). After a cut-off or a 5xx the audio may be made.
        audio = submit(lambda: self._req("POST", url, body=body, timeout=600, want="bytes"))
        if not audio:
            raise ProviderError("ElevenLabs returned no audio")
        with open(out, "wb") as f:
            f.write(audio)
        # Billed in characters on the user's plan, not dollars, so cost is left unknown.
        return Result([out], None, body["model_id"])
