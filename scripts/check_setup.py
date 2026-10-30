"""Stage 00: see which tools fill which slot, and save the choice. Free: makes no generations.

    check_setup.py                         show slots, API keys found, local tools
    check_setup.py --auto                  fill empty slots with the API keys found
    check_setup.py --set video=api:kie     choose a tool for a slot (api:kie, api:replicate, api:higgsfield, ...)
    check_setup.py --set video=mcp:<tool name> --set music=manual:Suno --set lipsync=none
    check_setup.py --set image=api:kie:nano-banana-pro      (pin a model)
    check_setup.py --set video=api:replicate:google/veo-3.1-fast --set image=mcp:higgsfield
    check_setup.py --voice-id <id>         save the chosen voice
    check_setup.py --limit 15              block any single run over $15 (--limit 0 removes it)

MCP tools can't be seen from Python: Claude looks at its own tools and saves them here with --set.
"""
import argparse
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers
from common import SETTINGS, SLOTS, ffmpeg, load_settings, save_settings

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--set", action="append", default=[], metavar="SLOT=MODE[:NAME[:MODEL]]")
ap.add_argument("--auto", action="store_true")
ap.add_argument("--voice-id")
ap.add_argument("--limit", type=float)
a = ap.parse_args()

s = load_settings()
changed = False

for item in a.set:
    slot, _, spec = item.partition("=")
    if slot not in SLOTS:
        sys.exit(f"Unknown slot '{slot}'. Slots: {', '.join(SLOTS)}")
    mode, _, rest = spec.partition(":")
    name, _, model = rest.partition(":")
    keep = {k: v for k, v in s[slot].items() if k in ("max_seconds", "voice_id", "quality")}
    if mode == "api":
        p = providers.get(name)
        if slot not in p.slots:
            sys.exit(f"{p.label} can't do {slot}. It does: {', '.join(p.slots)}")
        s[slot] = {**keep, "mode": "api", "provider": name, **({"model": model} if model else {})}
    elif mode in ("mcp", "manual"):
        s[slot] = {**keep, "mode": mode, **({"tool": rest} if rest else {})}
    elif mode == "none":
        s[slot] = {**keep, "mode": "none"}
    else:
        sys.exit(f"Mode must be api, mcp, manual or none (got '{mode}')")
    changed = True

if a.voice_id:
    s["voice"]["voice_id"] = a.voice_id
    changed = True
if a.limit is not None:
    s["spend_limit_per_run"] = a.limit or None
    changed = True

# ---- API keys ----
print("API keys found")
working = {}
col = max(len(c.label) for c in providers.ALL.values()) + 1
for name, cls in providers.ALL.items():          # registry order = preference order for --auto
    p = cls()
    if not p.has_key():
        print(f"  {p.label:{col}} no key ({p.env_key}, get one at {p.signup})")
        continue
    try:
        print(f"  {p.label:{col}} {p.check()}")
        working[name] = p
    except Exception as e:
        print(f"  {p.label:{col}} KEY PROBLEM: {e}")

if a.auto:
    for slot in SLOTS:
        if s[slot].get("mode", "none") != "none":
            continue
        for name, p in working.items():
            if p.can(slot):
                s[slot] = {**s[slot], "mode": "api", "provider": name}
                changed = True
                break

if changed:
    save_settings(s)
    print(f"\nSaved to {SETTINGS}")

# ---- slots ----
print("\nSlots")
for slot in SLOTS:
    c = s[slot]
    mode = c.get("mode", "none")
    if mode == "api":
        what = f"API: {c.get('provider')}" + (f" ({c['model']})" if c.get("model") else "")
    elif mode in ("mcp", "manual"):
        what = f"{mode.upper()}" + (f": {c['tool']}" if c.get("tool") else "")
    else:
        what = "not set"
    extra = f"  voice {c['voice_id']}" if slot == "voice" and c.get("voice_id") else ""
    print(f"  {slot:8} {what}{extra}")
lim = s.get("spend_limit_per_run")
print(f"  spend limit per run: {'$%.2f' % lim if lim else 'none'}")

# ---- local tools ----
print("\nLocal tools")
ok = True
ff = ffmpeg()
print(f"  ffmpeg          {ff or 'MISSING, install with: pip3 install imageio-ffmpeg'}")
ok &= bool(ff)
fw = importlib.util.find_spec("faster_whisper") is not None
print(f"  faster-whisper  {'OK' if fw else 'MISSING, install with: pip3 install faster-whisper'}")
ok &= fw
print(f"  python          {sys.version.split()[0]}")
if not ok:
    sys.exit(1)
