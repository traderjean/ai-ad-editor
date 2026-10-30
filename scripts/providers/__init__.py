"""Registry of API adapters. To add one: drop a file here with a Provider subclass and add it to ALL."""
from ._base import OutOfCredit, Provider, ProviderError, Result
from .elevenlabs import ElevenLabs
from .higgsfield import Higgsfield
from .kie import Kie
from .replicate import Replicate

# Order = preference when setup fills slots automatically (a direct ElevenLabs key wins the voice slot,
# then Kie, then Replicate, then Higgsfield).
ALL = {p.name: p for p in (ElevenLabs, Kie, Replicate, Higgsfield)}


def get(name):
    if name not in ALL:
        raise ProviderError(f"Unknown provider '{name}'. Available: {', '.join(sorted(ALL))}")
    return ALL[name]()


def for_slot(slot):
    """Adapters that can fill this slot."""
    return [p for p in ALL.values() if slot in p.slots]

__all__ = ["ALL", "OutOfCredit", "Provider", "ProviderError", "Result", "get", "for_slot"]
