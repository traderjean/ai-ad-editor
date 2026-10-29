"""A shot map to send with every draft: one picture of every shot with its time, id and line,
so notes like "at 0:23" or "the bathroom bit" can be matched to a shot.

    shot_map.py <project> <final file> [--shots shots.json]

Writes <final file without .mp4>_shotmap.jpg next to the draft and prints the same list as text.
Times are taken from the shots file; frames are taken from the draft itself (what the viewer saw).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_font, mmss, run_ffmpeg

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("final")
ap.add_argument("--shots", default="shots.json")
ap.add_argument("--cols", type=int, default=6)
a = ap.parse_args()

from PIL import Image, ImageDraw

with open(os.path.join(a.project, a.shots)) as f:
    shots = json.load(f)["shots"]
final = a.final if os.path.isabs(a.final) else os.path.join(a.project, a.final)
tmp = os.path.join(a.project, "qc", "shotmap")
os.makedirs(tmp, exist_ok=True)

TW, TH, PAD, TXT = 220, 391, 10, 120
font, small = load_font(22), load_font(17)
cells = []
for s in shots:
    mid = (s["start"] + s["end"]) / 2
    fp = os.path.join(tmp, s["id"] + ".jpg")
    run_ffmpeg(["-ss", f"{mid:.2f}", "-i", final, "-frames:v", "1", "-vf", f"scale={TW}:{TH}", fp])
    cells.append((s, Image.open(fp).convert("RGB")))
    print(f'{mmss(s["start"])}-{mmss(s["end"])}  {s["id"]}  {s.get("text", "")}')


def wrap(text, width=21, lines=4):
    out, line = [], ""
    for w in text.split():
        if len(line) + len(w) > width:
            out.append(line.strip())
            line = ""
        line += w + " "
    out.append(line.strip())
    return out[:lines]


rows = (len(cells) + a.cols - 1) // a.cols
sheet = Image.new("RGB", (a.cols * (TW + PAD) + PAD, rows * (TH + TXT + PAD) + PAD), "white")
draw = ImageDraw.Draw(sheet)
for i, (s, im) in enumerate(cells):
    x = PAD + (i % a.cols) * (TW + PAD)
    y = PAD + (i // a.cols) * (TH + TXT + PAD)
    sheet.paste(im, (x, y))
    draw.text((x, y + TH + 4), f'{mmss(s["start"])}  {s["id"]}', fill="black", font=font)
    draw.multiline_text((x, y + TH + 32), "\n".join(wrap(s.get("text", ""))), fill="#444", font=small, spacing=3)
out = os.path.splitext(final)[0] + "_shotmap.jpg"
sheet.save(out, quality=85)
print("saved", out)
