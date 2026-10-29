"""Final checks on every finished file before it goes to anyone.

    qc.py <project> [--platform meta|tiktok|youtube] [--files final/a.mp4 ...] [--shots shots.json]

For each file in final/ (previews skipped):
  - size and shape: 1080 wide, the right height for its name (9x16 / 4x5 / 1x1 / 16x9)
  - H.264 video, AAC sound, the sound runs the full length
  - no black frames longer than 0.5s, no frozen picture longer than 2s
  - length within the platform's ad limit, file size under its upload limit
  - the voiceover check (verify_vo.py) on 9:16 files when there is a voiceover
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
ap.add_argument("--platform", default="meta", choices=sorted(PLATFORMS))
ap.add_argument("--files", nargs="*")
ap.add_argument("--shots", help="force one shots file for every file (default: matched by hook name)")
a = ap.parse_args()

files = [os.path.join(a.project, f) for f in a.files] if a.files else \
    sorted(f for f in glob.glob(os.path.join(a.project, "final", "*.mp4")) if "preview" not in os.path.basename(f))
if not files:
    sys.exit("No finished files in final/.")
max_len, max_mb = PLATFORMS[a.platform]


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
    with open(path) as f:
        return rel, json.load(f)


def probe(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    v = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5})", r)
    au = re.search(r"Audio: (\w+)", r)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r)
    length = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return (v.group(1) if v else None, int(v.group(2)) if v else 0, int(v.group(3)) if v else 0,
            au.group(1) if au else None, length)


def detect(path):
    """(black stretches, frozen stretches, sound length) in one pass."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-vf",
                        "blackdetect=d=0.5:pix_th=0.08,freezedetect=n=0.002:d=2", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r)
    frozen = re.findall(r"freeze_start: ([\d.]+)", r)
    r2 = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-map", "0:a", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    t = re.findall(r"time=(\d+):(\d+):([\d.]+)", r2)
    snd = int(t[-1][0]) * 3600 + int(t[-1][1]) * 60 + float(t[-1][2]) if t else 0
    return black, frozen, snd


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
    black, frozen, snd = detect(path)
    for s, e in black:
        if float(s) < length - 0.5:       # a fade at the very end is fine
            problems.append(f"black picture {float(s):.1f}s to {float(e):.1f}s")
    for s in frozen:
        notes.append(f"picture doesn't move for 2s+ from {float(s):.1f}s (fine for a still or end card; check it)")
    if abs(snd - length) > 0.3:
        problems.append(f"sound is {snd:.1f}s, video is {length:.1f}s")
    rel, plan = shots_for(name)
    if shape == "9x16" and plan.get("vo"):
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_vo.py"),
                            a.project, path, "--shots", rel], capture_output=True, text=True)
        line = (r.stdout.strip().splitlines() or ["(no output)"])
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
with open(os.path.join(a.project, "qc", "report.md"), "w") as f:
    f.write("\n".join(report) + "\n")
print(f"\n{len(files) - failed}/{len(files)} passed. Report: qc/report.md")
sys.exit(1 if failed else 0)
