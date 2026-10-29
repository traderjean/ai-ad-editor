"""ElevenLabs: voiceovers. Default model eleven_v3 (most natural, supports [audio tags])."""
import urllib.parse

from ._base import Provider, ProviderError, Result, http, with_retries

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

    def check(self):
        # Restricted keys often lack user_read, so fall back to the voice list, then report what's missing.
        try:
            d = http("GET", f"{API}/v1/user/subscription", headers=self._h())
            used, limit = d.get("character_count", 0), d.get("character_limit", 0)
            return f"key OK, {d.get('tier', '?')} plan, {limit - used:,} characters left this month"
        except ProviderError as e:
            if e.code != 401:
                raise
        try:
            return f"key OK, {len(self.voices())} voices available (restricted key: no plan info)"
        except ProviderError as e:
            if e.code != 401:
                raise
        return "key set, but restricted: can't list voices for free. Text to speech may still work; pass --voice <id>"

    def voices(self):
        d = http("GET", f"{API}/v1/voices", headers=self._h())
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
        body = {"text": text, "model_id": model or "eleven_v3", "voice_settings": s}
        url = f"{API}/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=mp3_44100_128"
        audio = with_retries(lambda: http("POST", url, headers=self._h(), body=body, timeout=600, want="bytes"))
        if not audio:
            raise ProviderError("ElevenLabs returned no audio")
        with open(out, "wb") as f:
            f.write(audio)
        # Billed in characters on the user's plan, not dollars, so cost is left unknown.
        return Result([out], None, body["model_id"])
