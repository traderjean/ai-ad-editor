"""Final checks on every finished file before it goes to anyone.

    qc.py <project> [--platform meta|tiktok|youtube] [--files final/a.mp4 ...] [--shots shots.json]

For the newest take of each file in final/ (previews and older _v<n> takes skipped):
  - size and shape: 1080 wide, the right height for its name (9x16 / 4x5 / 1x1 / 16x9)
  - H.264 video, AAC sound, the sound and the picture both run the full length
  - no black frames longer than 0.5s (a dark text card is only noted), no frozen picture longer than 2s
  - length within the platform's ad limit, file size under its upload limit
  - the voiceover check (verify_vo.py) on 9:16 files when the ad speaks (a voiceover, an avatar, clip voices)
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
from common import ffmpeg

PLATFORMS = {   # max ad length (s), max file size (MB)
    "meta": (240 * 60, 4000),
    "tiktok": (10 * 60, 500),
    "youtube": (60, 4000),          # Shorts
}
SHAPES = {"9x16": (1080, 1920), "4x5": (1080, 1350), "1x1": (1080, 1080), "16x9": (1920, 1080)}

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


if a.files:
    files = [in_project(f) for f in a.files]
    gone = [f for f in files if not os.path.exists(f)]
    if gone:
        sys.exit(f"No such file: {', '.join(gone)} (give it from the project folder or from the working folder).")
else:
    newest = {}                 # older _v<n> takes stay in final/ for history; check the newest of each
    for f in glob.glob(os.path.join(a.project, "final", "*.mp4")):
        if os.path.basename(f).startswith("preview_"):
            continue
        m = re.match(r"(.*)_v(\d+)\.mp4$", os.path.basename(f))
        key, n = (m.group(1), int(m.group(2))) if m else (f, 0)
        if key not in newest or n > newest[key][0]:
            newest[key] = (n, f)
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
    with open(path, encoding="utf-8") as f:
        return rel, json.load(f)


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


def detect(path):
    """(black stretches, frozen stretches, picture length, sound length)."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-map", "0:v:0", "-vf",
                        "blackdetect=d=0.5:pix_th=0.08,freezedetect=n=0.002:d=2", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r)
    frozen = re.findall(r"freeze_start: ([\d.]+)", r)
    r2 = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-map", "0:a", "-f", "null", "-"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return black, frozen, played(r), played(r2)


def text_cards(plan, length):
    """(start, end) of the plan's text cards, back-to-back cards joined into one stretch. A card that is the
    last shot runs on to the end card, or to the end of the file, as edit.py plays it."""
    spans, shots = [], plan.get("shots", [])
    for s in shots:
        if s.get("type") == "text":
            end = s["end"]
            if s is shots[-1]:
                end = max(end, length - (plan["endcard"].get("seconds", 3) if plan.get("endcard") else 0))
            if spans and abs(spans[-1][1] - s["start"]) < 0.05:
                spans[-1][1] = end
            else:
                spans.append([s["start"], end])
    return spans


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
    black, frozen, pic, snd = detect(path)
    rel, plan = shots_for(name)
    cards = text_cards(plan, length)
    for s, e in ((float(s), float(e)) for s, e in black):
        if s >= length - 0.5:       # a fade at the very end is fine
            continue
        if any(c0 - 0.2 <= s and e <= c1 + 0.2 for c0, c1 in cards):   # white text on a dark card reads as black
            notes.append(f"dark text card {s:.1f}s to {e:.1f}s (fine if the text shows; check a frame)")
        else:
            problems.append(f"black picture {s:.1f}s to {e:.1f}s")
    for s in frozen:
        notes.append(f"picture doesn't move for 2s+ from {float(s):.1f}s (fine for a still or end card; check it)")
    if abs(snd - length) > 0.3:
        problems.append(f"sound is {snd:.1f}s, file is {length:.1f}s")
    if abs(pic - length) > 0.3:
        problems.append(f"picture is {pic:.1f}s, file is {length:.1f}s")
    speaks = plan.get("vo") or any(s.get("use_clip_audio") or s.get("type") == "avatar" for s in plan.get("shots", []))
    if shape == "9x16" and speaks:
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
