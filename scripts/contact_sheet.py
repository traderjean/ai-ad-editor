"""Contact sheet for checking clips: 3 frames (start / middle / end) per clip, one row per shot.

    contact_sheet.py <project> [--shots shots.json] [--only s01 s02]

Writes <project>/qc/contact_sheet.jpg (frames kept in qc/ for a closer look) and flags clips whose
first second barely moves (a frozen or storyboard start, so the edit should start later with "in").
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clip_path, duration, ffmpeg, load_font, run_ffmpeg

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--only", nargs="*")
ap.add_argument("--shots", default="shots.json")
a = ap.parse_args()

from PIL import Image, ImageDraw

with open(os.path.join(a.project, a.shots), encoding="utf-8") as f:
    shots = json.load(f)["shots"]
qc = os.path.join(a.project, "qc")
os.makedirs(qc, exist_ok=True)


def frozen_start(clip):
    """Seconds at the start where the picture doesn't change (0 if it moves straight away)."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-t", "2", "-i", clip, "-vf", "freezedetect=n=0.003:d=0.4",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    start = end = None
    for line in r.stderr.splitlines():
        if "freeze_start" in line and start is None:
            start = float(line.split("freeze_start:")[1].split()[0])
        if "freeze_end" in line and end is None:
            end = float(line.split("freeze_end:")[1].split()[0])
    if start is not None and start < 0.1:
        return end if end is not None else 2.0
    return 0.0


rows, flags = [], []
for s in shots:
    clip = clip_path(a.project, s)
    if (a.only and s["id"] not in a.only) or not clip or not os.path.exists(clip):
        continue
    d = duration(clip)
    frames = []
    for k, t in enumerate([0.2, d / 2, max(d - 0.3, 0)]):
        fp = os.path.join(qc, f'{s["id"]}_{k}.jpg')
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=360:-2", fp])
        frames.append(Image.open(fp))
    fz = frozen_start(clip)
    if fz:
        flags.append(f'{s["id"]}: first {fz:.1f}s barely moves; set "in": {fz:.1f} on this shot if it shows')
    rows.append((s, frames))

if not rows:
    sys.exit("No clips found.")
tw, th = rows[0][1][0].size
label_w = 420
sheet = Image.new("RGB", (label_w + 3 * tw, len(rows) * th), "white")
draw = ImageDraw.Draw(sheet)
font = load_font(22)
for r, (s, frames) in enumerate(rows):
    y = r * th
    for k, im in enumerate(frames):
        sheet.paste(im.resize((tw, th)), (label_w + k * tw, y))
    lines, line = [], ""
    for w in s.get("text", "").split():
        if len(line) + len(w) > 30:
            lines.append(line)
            line = ""
        line += w + " "
    lines.append(line)
    draw.text((16, y + 16), s["id"], fill="black", font=font)
    draw.multiline_text((16, y + 52), "\n".join(lines[:12]), fill="#333", font=font, spacing=6)
    draw.line([(0, y), (sheet.width, y)], fill="#ccc", width=2)
name = "contact_sheet.jpg" if a.shots == "shots.json" else "contact_sheet_" + a.shots.replace(".json", ".jpg")
out = os.path.join(qc, name)
sheet.save(out, quality=85)
print("saved", out, f"({len(rows)} shots)")
for f in flags:
    print("  CHECK:", f)
