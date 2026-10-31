"""Final checks on every finished file before it goes to anyone.

    qc.py <project> [--platform meta|tiktok|youtube] [--files final/a.mp4 ...] [--shots shots.json]

For the newest take of each file in final/ (previews and older _v<n> takes skipped):
  - size and shape: 1080 wide, the right height for its name (9x16 / 4x5 / 1x1 / 16x9)
  - H.264 video, AAC sound, the sound and the picture both run the full length
  - no black frames longer than 0.5s (a dark text card or end card is only noted)
  - on 9:16 files, no clip shot whose picture stands still for 1s or more (a clip shorter than its shot, a frozen
    start); stills, text cards and the end card may hold still, and so may a shot with "freeze_ok": true
  - sizes (4x5 / 1x1 / 16x9) made from the newest 9:16, not from an older take of it
  - length within the platform's ad limit, file size under its upload limit
  - the voiceover check (verify_vo.py) on every 9:16 file, with its notes
The platform is --platform, else "platform" in shots.json, else meta.
Writes qc/report.md and exits 1 if anything fails.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CLIP_TYPES, clip_path, ffmpeg

PLATFORMS = {   # max ad length (s), max file size (MB)
    "meta": (240 * 60, 4000),
    "tiktok": (10 * 60, 500),
    "youtube": (180, 4000),         # Shorts: up to 3 min since Oct 2024 (checked Oct 2026)
}
SHAPES = {"9x16": (1080, 1920), "4x5": (1080, 1350), "1x1": (1080, 1080), "16x9": (1920, 1080)}
MOVING = CLIP_TYPES + ("avatar", "library", "footage")      # shot types that should never stand still

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--platform", choices=sorted(PLATFORMS), help='default: "platform" in shots.json, else meta')
ap.add_argument("--files", nargs="*")
ap.add_argument("--shots", help="force one shots file for every file (default: matched by hook name)")
a = ap.parse_args()


def in_project(f):
    """A file given from the project folder (final/a.mp4), else from the working folder (<project>/final/a.mp4)."""
    p = os.path.join(a.project, f)
    return p if os.path.exists(p) or not os.path.exists(f) else f


newest = {}                 # older _v<n> takes stay in final/ for history; check the newest of each
for f in glob.glob(os.path.join(glob.escape(a.project), "final", "*.mp4")):
    if os.path.basename(f).startswith("preview_"):
        continue
    m = re.match(r"(.*)_v(\d+)\.mp4$", os.path.basename(f))
    key, n = (m.group(1), int(m.group(2))) if m else (f, 0)
    if key not in newest or n > newest[key][0]:
        newest[key] = (n, f)
if a.files:
    files = [in_project(f) for f in a.files]
    gone = [f for f in files if not os.path.exists(f)]
    if gone:
        sys.exit(f"No such file: {', '.join(gone)} (give it from the project folder or from the working folder).")
else:
    files = sorted(f for _, f in newest.values())
if not files:
    sys.exit("No finished files in final/.")


def shots_for(name):
    """The plan a final was cut from: <project>_hookB_... -> shots_hookB.json, hookA -> shots.json."""
    if a.shots:
        rel = a.shots
    else:
        m = re.search(r"_(hook\w+?)_(?:9x16|4x5|1x1|16x9)_", name)
        rel = f"shots_{m.group(1)}.json" if m and os.path.exists(os.path.join(a.project, f"shots_{m.group(1)}.json")) \
            else "shots.json"
    path = os.path.join(a.project, rel)
    if not os.path.exists(path):
        return rel, {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            plan = json.load(f)
    except (OSError, ValueError) as e:
        if rel not in told:
            told.add(rel)
            print(f"NOTE {rel} can't be read ({e}): fix it and run this again (checked without it).")
        return rel, {}
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
        if rel not in told:
            told.add(rel)
            print(f'NOTE {rel} isn\'t a shots file (it should hold {{"shots": [...]}}): checked without it.')
        return rel, {}
    return rel, plan


told = set()


def rel_to_project(path):
    try:
        return os.path.relpath(path, a.project)
    except ValueError:      # Windows: on another drive than the project
        return path


if not a.platform:      # the brief's platform, if the plan has it
    a.platform = (str(shots_for("")[1].get("platform", "meta")).lower().split() or ["meta"])[0]   # "YouTube Shorts" too
    if a.platform not in PLATFORMS:
        sys.exit(f'"platform" in the shots file is "{a.platform}"; use one of: {", ".join(sorted(PLATFORMS))}.')
max_len, max_mb = PLATFORMS[a.platform]


def probe(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stderr
    v = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5})", r)
    au = re.search(r"Audio: (\w+)", r)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r)
    length = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return (v.group(1) if v else None, int(v.group(2)) if v else 0, int(v.group(3)) if v else 0,
            au.group(1) if au else None, length)


def played(r):
    """How far ffmpeg got (its last time=), in seconds."""
    t = re.findall(r"time=(\d+):(\d+):([\d.]+)", r)
    return int(t[-1][0]) * 3600 + int(t[-1][1]) * 60 + float(t[-1][2]) if t else 0


def detect(path, still_check):
    """(black stretches, frozen stretches, picture length, sound length). Frozen picture is looked for only above
    and below the band captions can sit in (30%-86% of the height): a caption changing words over a frozen
    clip would hide it. A frozen stretch still going at the end has None for its end."""
    vf = "[0:v]blackdetect=d=0.5:pix_th=0.08"
    if still_check:
        vf += (",split[a][b];[a]crop=iw:ih*0.29:0:0[t];[b]crop=iw:ih*0.13:0:ih*0.87[u];"
               "[t][u]vstack,freezedetect=n=0.002:d=1")
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-filter_complex", vf, "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r)
    frozen = []
    for kind, t in re.findall(r"freeze_(start|end): ([\d.]+)", r):
        if kind == "start":
            frozen.append([float(t), None])
        elif frozen:
            frozen[-1][1] = float(t)
    r2 = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-map", "0:a", "-f", "null", "-"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return black, frozen, played(r), played(r2)


def still_share(path, t0, t1):
    """How much of t0..t1 the middle of the picture (where captions sit) stands still too, between caption
    changes: most of it for a frozen clip, next to none for one that moves only there (a still background)."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", path,
                        "-map", "0:v:0", "-vf", "crop=iw:ih*0.57:0:ih*0.29,freezedetect=n=0.0002:d=0.1",
                        "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    still, start = 0.0, None
    for kind, t in re.findall(r"freeze_(start|end): ([\d.]+)", r):
        if kind == "start":
            start = float(t)
        elif start is not None:
            still, start = still + float(t) - start, None
    if start is not None:
        still += t1 - t0 - start
    return still / max(t1 - t0, 0.001)


def timeline(plan, length):
    """(start, end, shot) of each shot as edit.py plays it: the last one runs on to the end card, or to the end
    of the file."""
    shots = [s for s in plan.get("shots", []) if isinstance(s, dict) and isinstance(s.get("id"), str) and all(
        isinstance(s.get(k), (int, float)) for k in ("start", "end"))]
    ec = plan["endcard"].get("seconds", 3) if isinstance(plan.get("endcard"), dict) else 0
    return [(s["start"], max(s["end"], length - ec) if s is shots[-1] else s["end"], s) for s in shots]


def text_cards(plan, length):
    """(start, end) of the plan's text cards, back-to-back cards joined into one stretch."""
    spans = []
    for start, end, s in timeline(plan, length):
        if s.get("type") == "text":
            if spans and abs(spans[-1][1] - start) < 0.05:
                spans[-1][1] = end
            else:
                spans.append([start, end])
    return spans


def clip_of(s):
    """The video file a shot plays (None for stills, text cards and a shot missing its "source")."""
    try:
        return clip_path(a.project, s)
    except (KeyError, TypeError):
        return None


def last_word(plan, rel):
    """When the last word ends (s), from the plan's word timings; None if they can't be read."""
    m = re.match(r"shots_(hook\w+)\.json$", os.path.basename(rel))
    words = plan.get("words") or (f"words_{m.group(1)}.json" if m and os.path.exists(
        os.path.join(a.project, f"words_{m.group(1)}.json")) else "words.json")
    try:
        with open(os.path.join(a.project, words), encoding="utf-8-sig") as f:
            return max(float(w["e"]) for w in json.load(f))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def stills(path, plan, rel, frozen, length):
    """(problems, notes) for the frozen stretches: a clip shot standing still 0.5s or more is a problem unless
    it has "freeze_ok", or it is the last shot holding after the last word. Stills, text cards and the end card
    may hold still."""
    problems, notes = [], []
    spans = timeline(plan, length)
    for fs, fe in frozen:
        fe = length if fe is None else fe
        if not spans:
            why = "has no shots with a start and end" if os.path.exists(os.path.join(a.project, rel)) else "not found"
            notes.append(f"picture doesn't move from {fs:.1f}s to {fe:.1f}s ({rel} {why}, so a still can't be "
                         "told from a frozen clip; look at it)")
        for s0, s1, s in spans:
            held = min(fe, s1) - max(fs, s0)
            sid, src = s["id"], clip_of(s)
            if held < 0.5 or s.get("type", "clip") not in MOVING or not src or not os.path.exists(src):
                continue
            a0, a1 = max(fs, s0), min(fe, s1)
            if s.get("freeze_ok"):
                notes.append(f'{sid} holds still {a0:.1f}s to {a1:.1f}s ("freeze_ok" is set on it)')
            elif s is spans[-1][2] and (last_word(plan, rel) or length) <= a0 + 0.05:
                notes.append(f"{sid} holds still from {a0:.1f}s, after the last word (fine for a closing shot; "
                             "look at it)")
            elif still_share(path, a0, a1) >= 0.5:
                if a0 <= s0 + 0.1 and a1 >= s1 - 0.1:
                    why = f"the whole shot stands still: look at {rel_to_project(src)}"
                elif a1 >= s1 - 0.1:
                    why = ('its clip runs out before the shot ends. Set a smaller "in", shorten the shot or remake '
                           "the clip")
                elif a0 <= s0 + 0.1:
                    start_in = s.get("in", s0 if s.get("type") in ("avatar", "footage") else 0)
                    why = (f'its clip starts frozen. Set "in": {start_in + held * s.get("speed", 1):.1f} on {sid} '
                           "(contact_sheet.py shows it)")
                else:
                    why = "its clip stands still mid-shot. Look at it"
                problems.append(f"{sid}: picture frozen {a0:.1f}s to {a1:.1f}s ({held:.1f}s of its {s1 - s0:.1f}s): "
                                f'{why}, then run edit.py again ("freeze_ok": true on the shot if it\'s meant to '
                                "hold still)")
    return problems, notes


def stale_size(path):
    """Why a 4x5 / 1x1 / 16x9 file is out of date with the newest 9:16 of its ad, else None."""
    m = re.match(r"(.*)_(4x5|1x1|16x9)_v(\d+)\.mp4$", os.path.basename(path))
    main = newest.get(f"{m.group(1)}_9x16") if m else None
    if not main:
        return None
    again = f"Make the sizes again: variants.py {a.project} --sizes {m.group(2)}"
    if main[0] > int(m.group(3)):
        return f"made from an older cut: this is v{m.group(3)}, the newest 9:16 is v{main[0]}. {again}"
    if main[0] == int(m.group(3)) and os.path.getmtime(path) < os.path.getmtime(main[1]) - 1:
        return f"made before {os.path.basename(main[1])} was cut again. {again}"
    return None


report, failed = [f"# QC report ({a.platform})", ""], 0
for path in files:
    name = os.path.basename(path)
    problems, notes = [], []
    vcodec, wd, ht, acodec, length = probe(path)
    shape = next((k for k in SHAPES if f"_{k}_" in name), "9x16")
    if (wd, ht) != SHAPES[shape]:
        problems.append(f"size {wd}x{ht}, expected {SHAPES[shape][0]}x{SHAPES[shape][1]} for {shape}")
    if vcodec != "h264":
        problems.append(f"video is {vcodec}, should be h264")
    if acodec != "aac":
        problems.append(f"sound is {acodec}, should be aac")
    if length > max_len:
        problems.append(f"{length:.0f}s is over {a.platform}'s {max_len}s limit")
    mb = os.path.getsize(path) / 1e6
    if mb > max_mb:
        problems.append(f"{mb:.0f}MB is over {a.platform}'s {max_mb}MB limit")
    black, frozen, pic, snd = detect(path, shape == "9x16")      # the other sizes are crops of the 9:16
    rel, plan = shots_for(name)
    cards = text_cards(plan, length)
    ec = plan["endcard"].get("seconds", 3) if isinstance(plan.get("endcard"), dict) else 0
    for s, e in ((float(s), float(e)) for s, e in black):
        if s >= length - 0.5:       # a fade at the very end is fine
            continue
        if any(c0 - 0.2 <= s and e <= c1 + 0.2 for c0, c1 in cards):   # white text on a dark card reads as black
            notes.append(f"dark text card {s:.1f}s to {e:.1f}s (fine if the text shows; check a frame)")
        elif ec and s >= length - ec - 0.2:      # a logo on black reads as black too
            notes.append(f"dark end card {s:.1f}s to {e:.1f}s (fine if the logo shows; check a frame)")
        else:
            problems.append(f"black picture {s:.1f}s to {e:.1f}s")
    p, n = stills(path, plan, rel, frozen, length)
    problems += p
    notes += n
    if shape == "9x16":
        notes += [f"{s['id']} has no clip yet: its start frame plays as a still (make it: generate.py clips . "
                  f"--only {s['id']}, then edit.py)" for _, _, s in timeline(plan, length)
                  if s.get("type", "clip") in CLIP_TYPES and not os.path.exists(clip_of(s))]
    stale = stale_size(path)
    if stale:
        problems.append(stale)
    if abs(snd - length) > 0.3:
        problems.append(f"sound is {snd:.1f}s, file is {length:.1f}s")
    if abs(pic - length) > 0.3:
        problems.append(f"picture is {pic:.1f}s, file is {length:.1f}s")
    if shape == "9x16":     # every 9:16 file: a plan with no speech passes fast, a stray words file is caught
        # absolute paths: verify_vo reads a relative file from the project folder, which would join it twice
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_vo.py"),
                            os.path.abspath(a.project), os.path.abspath(path), "--shots", rel],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        line = r.stdout.strip().splitlines() or r.stderr.strip().splitlines()[-3:] or ["(no output)"]
        if r.returncode != 0:
            problems.append("voiceover check: " + " | ".join(line))
        else:
            notes.append("voiceover check: " + line[0])
            notes += [x.strip() for x in line[1:] if x.strip()]      # its notes: unsure words, a changed word
    ok = not problems
    failed += not ok
    report.append(f"## {'PASS' if ok else 'FAIL'}  {name}")
    report.append(f"{wd}x{ht}, {length:.1f}s, {mb:.1f}MB")
    report += [f"- FAIL: {p}" for p in problems] + [f"- note: {n}" for n in notes] + [""]
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({wd}x{ht}, {length:.1f}s, {mb:.1f}MB)")
    for p in problems:
        print("    FAIL:", p)
    for n in notes:
        print("    note:", n)

os.makedirs(os.path.join(a.project, "qc"), exist_ok=True)
with open(os.path.join(a.project, "qc", "report.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(report) + "\n")
print(f"\n{len(files) - failed}/{len(files)} passed ({a.platform} limits). Report: qc/report.md")
sys.exit(1 if failed else 0)
