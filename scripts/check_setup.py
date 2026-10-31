"""Stage 00: see which tools fill which slot, and save the choice. Free: makes no generations.

    check_setup.py                         show slots, API keys found, local tools
    check_setup.py --auto                  fill empty slots with the API keys found
    check_setup.py --set video=api:kie     choose a tool for a slot (api:kie, api:replicate, api:higgsfield, ...)
    check_setup.py --set video=mcp:<tool name> --set music=manual:Suno --set lipsync=none
    check_setup.py --set image=api:kie:nano-banana-pro      (pin a model; mcp:<tool>:<model> pins one too)
    check_setup.py --set video=api:replicate:google/veo-3.1-fast --set image=mcp:higgsfield
    check_setup.py --voice-id <id>         save the chosen voice
    check_setup.py --limit 15              block any single run over $15 (--limit 0 removes it)
    check_setup.py --budget 40             run inside an ad's project folder: generate.py blocks any run that
                                           would take that ad past $40 in all (--budget 0 removes it)

MCP tools can't be seen from Python: Claude looks at its own tools and saves them here with --set.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers
from common import (BUDGET_FILE, FFMPEG_ENCODERS, FFMPEG_FILTERS, PROJECT_FILES, SETTINGS, SKILL_DIR, SLOTS, ffmpeg,
                    ffmpeg_fix, load_budget, load_settings, project_name, save_settings, spent)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--set", action="append", default=[], metavar="SLOT=MODE[:NAME[:MODEL]]")
ap.add_argument("--auto", action="store_true")
ap.add_argument("--voice-id")
ap.add_argument("--limit", type=float, help="most one run may cost, in USD (0 removes it)")
ap.add_argument("--budget", type=float, help="most this ad may cost in all, in USD (0 removes it); run it inside the project")
a = ap.parse_args()
if a.limit is not None and a.limit < 0:
    sys.exit("The per-run limit must be 0 or more (--limit 0 removes it).")
if a.budget is not None and a.budget < 0:
    sys.exit("The budget must be 0 or more (--budget 0 removes it).")
if a.budget is not None and os.path.abspath(os.getcwd()) in (SKILL_DIR, os.path.join(SKILL_DIR, "scripts")):
    sys.exit("Run --budget from inside the ad's project folder: the budget belongs to one ad.")


def adapter(name):
    try:
        return providers.get(name)
    except providers.ProviderError as e:
        sys.exit(str(e))


s = load_settings()
voice_was = s["voice"].get("provider") if s["voice"].get("mode") == "api" else None
changed = False

for item in a.set:
    slot, _, spec = item.partition("=")
    if slot not in SLOTS:
        sys.exit(f"Unknown slot '{slot}'. Slots: {', '.join(SLOTS)}")
    mode, _, rest = spec.partition(":")
    name, _, model = rest.partition(":")
    keep = {k: v for k, v in s[slot].items() if k in ("max_seconds", "voice_id", "quality")}
    if mode == "api":
        p = adapter(name)
        if slot not in p.slots:
            sys.exit(f"{p.label} can't do {slot}. It does: {', '.join(p.slots)}")
        if slot == "lipsync" and model:
            sys.exit("Lip-sync and avatar share this slot, so a model can't be pinned here. "
                     "Pick it per run with: generate.py lipsync (or avatar) --model <id>")
        s[slot] = {**keep, "mode": "api", "provider": name, **({"model": model} if model else {})}
    elif mode in ("mcp", "manual"):
        # mcp:<tool>[:<model>], like api: the model is printed with every job handed over
        s[slot] = {**keep, "mode": mode, **({"tool": name} if name else {}), **({"model": model} if model else {})}
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
working, broken = {}, {}
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
        broken[name] = e

if a.auto:
    held = {}                     # provider whose key couldn't be checked -> slots left empty because of it
    for slot in SLOTS:
        if s[slot].get("mode", "none") != "none":
            continue
        for name, cls in providers.ALL.items():
            if name in broken and slot in cls.slots:
                held.setdefault(name, []).append(slot)    # don't fall back to a later (often dearer) provider
                break
            p = working.get(name)
            if p and p.can(slot):
                s[slot] = {**s[slot], "mode": "api", "provider": name}
                changed = True
                break
    for name, slots in held.items():
        print(f"\nNot filled: {', '.join(slots)}. {providers.ALL[name].label.split(' (')[0]} has a key but it couldn't be "
              f"checked ({broken[name]}). Run check_setup.py --auto again, or choose with --set {slots[0]}=api:<name>.")

# A saved voice belongs to the provider it was picked on: check it against the new one (the lists are free).
v = s["voice"]
if v.get("mode") == "api" and v.get("voice_id") and (v.get("provider") != voice_was or a.voice_id):
    p = adapter(v["provider"])
    try:
        ok = v["voice_id"] in [x[0] for x in p.voices()]
        why = "isn't available on"
    except Exception as e:
        ok, why = bool(a.voice_id), f"couldn't be checked ({e}) on"    # keep one the user just typed
        if ok:
            print(f"\nVoice {v['voice_id']} {why} {p.label.split(' (')[0]}: it's saved, but check it with generate.py voices")
    if not ok:
        print(f"\nVoice {v.pop('voice_id')} {why} {p.label.split(' (')[0]}, so it wasn't kept: pick one with "
              f"generate.py voices, then save it with --voice-id <id>")
        changed = True

if changed:
    save_settings(s)
    print(f"\nSaved to {SETTINGS}")

# ---- budget for the ad in the working folder ----
here = os.getcwd()
if a.budget is not None:
    path = os.path.join(here, BUDGET_FILE)
    if a.budget:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"budget": a.budget}, f)
            f.write("\n")
        print(f"\nBudget for this ad ({project_name()}): ${a.budget:.2f}, saved to {path}")
        if not any(os.path.exists(os.path.join(here, x)) for x in PROJECT_FILES if x != BUDGET_FILE):
            print(f"  Note: {here} has no state.json, shots.json or brief.md. The budget covers the runs made from "
                  f"this folder: make sure it's the ad's project folder.")
    elif os.path.exists(path):
        os.remove(path)
        print(f"\nBudget removed for this ad ({project_name()})")
    else:
        print(f"\nNo budget was set for this ad ({project_name()})")

# ---- slots ----
print("\nSlots")
for slot in SLOTS:
    c = s[slot]
    mode = c.get("mode", "none")
    warn = ""
    if mode == "api":
        what = f"API: {c.get('provider')}" + (f" ({c['model']})" if c.get("model") else "")
        try:
            p = providers.get(c.get("provider", ""))
        except providers.ProviderError as e:
            warn = f"  WARNING: {e}. Choose again with --set {slot}=api:<name>"
        else:
            if not p.has_key():
                warn = f"  WARNING: {p.env_key} is not set, so generate.py will stop until it is (get a key at {p.signup})"
    elif mode in ("mcp", "manual"):
        what = f"{mode.upper()}" + (f": {c['tool']}" if c.get("tool") else "") + (f" ({c['model']})" if c.get("model") else "")
    else:
        what = "not set"
    extra = f"  voice {c['voice_id']}" if slot == "voice" and c.get("voice_id") else ""
    print(f"  {slot:8} {what}{extra}{warn}")
lim = s.get("spend_limit_per_run")
print(f"  spend limit per run: {'$%.2f' % lim if lim else 'none'}")
budget = load_budget()
if budget:
    done, unknown = spent()
    print(f"  budget for this ad ({project_name()}): ${budget:.2f}, ${done:.2f} spent so far"
          + (f" (plus {unknown} job(s) of unknown cost)" if unknown else ""))

# ---- local tools ----
print("\nLocal tools")
ok = True
ff = ffmpeg()
print(f"  ffmpeg          {ff or 'MISSING, install with: pip3 install imageio-ffmpeg'}")
ok &= bool(ff)
if ff:
    # A cut-down build (no H.264, no captions) would only fail at the edit, after the clips are paid for.
    def names(kind):
        try:
            r = subprocess.run([ff, "-hide_banner", f"-{kind}"], capture_output=True, text=True, timeout=30,
                               encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return set()
        return {line.split()[1] for line in r.stdout.splitlines() if len(line.split()) > 1}
    missing = [x for x in FFMPEG_ENCODERS if x not in names("encoders")] + \
              [x for x in FFMPEG_FILTERS if x not in names("filters")]
    if missing:
        print(f"  ffmpeg is missing {', '.join(missing)}. {ffmpeg_fix(ff)}")
        ok = False
fw = importlib.util.find_spec("faster_whisper") is not None
print(f"  faster-whisper  {'OK' if fw else 'MISSING, install with: pip3 install faster-whisper'}")
ok &= fw
print(f"  python          {sys.version.split()[0]}")
if not ok:
    sys.exit(1)
