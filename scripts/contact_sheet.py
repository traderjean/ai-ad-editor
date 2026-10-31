"""Contact sheet for checking clips: 3 frames (start / middle / end) per clip, 6 clips to a page.

    contact_sheet.py <project> [--shots shots.json] [--only s01 s02]

Writes <project>/qc/contact_sheet.jpg (contact_sheet_1.jpg, _2.jpg ... when there are more than 6 clips; look
at every page; frames kept in qc/ for a closer look). Each frame keeps its clip's own shape. Flags clips whose
first second barely moves (a frozen or storyboard start, so the edit should start later with "in") and clips
too short for their shot (the end would freeze).
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clip_path, duration, ffmpeg, load_font, mmss, run_ffmpeg

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--only", nargs="*")
ap.add_argument("--shots", default="shots.json")
a = ap.parse_args()

from PIL import Image, ImageDraw, ImageOps

try:
    with open(os.path.join(a.project, a.shots), encoding="utf-8-sig") as f:
        shots = [s for s in json.load(f)["shots"] if isinstance(s, dict) and s.get("id")]
except (OSError, ValueError, KeyError, TypeError) as e:
    sys.exit(f"Can't read the shots in {os.path.join(a.project, a.shots)} ({e}). Write or fix it, then run this again.")
qc = os.path.join(a.project, "qc")
os.makedirs(qc, exist_ok=True)

PER_PAGE, FH, FW, GAP, LABEL, PAGE_W, PAGE_H = 6, 400, 480, 8, 86, 1500, 1600   # frames fit in FW x FH, own shape
font, small = load_font(24), load_font(19)


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


def frame(clip, t, fp):
    """One frame at t seconds, fitted into FW x FH in its own shape; a grey box if there is none."""
    if os.path.exists(fp):      # left by an earlier run: never show it for this clip
        os.remove(fp)
    try:
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", "-vf",
                    f"scale={FW}:{FH}:force_original_aspect_ratio=decrease", fp])
        with Image.open(fp) as im:
            return ImageOps.contain(im.convert("RGB"), (FW, FH))
    except (SystemExit, OSError):
        return Image.new("RGB", (FH * 9 // 16, FH), "#999")


def wrap(text, width):
    lines, line = [], ""
    for w in text.split():
        if line and small.getlength(f"{line} {w}") > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return lines + [line] if line else lines


rows, flags, missing = [], [], []
for s in shots:
    if a.only and s["id"] not in a.only:
        continue
    try:
        clip = clip_path(a.project, s)
    except KeyError:        # a library / avatar shot with no "source" yet
        clip = None
    if not clip:
        continue
    if not os.path.exists(clip):
        missing.append(s["id"])
        continue
    try:
        d = duration(clip)
    except SystemExit:
        flags.append(f'{s["id"]}: {os.path.relpath(clip, a.project)} can\'t be read (broken or cut off): remake it')
        continue
    frames = [frame(clip, t, os.path.join(qc, f'{s["id"]}_{k}.jpg'))
              for k, t in enumerate([min(0.2, d / 2), d / 2, max(d - 0.3, 0)])]
    fz = frozen_start(clip)
    if fz:
        flags.append(f'{s["id"]}: first {fz:.1f}s barely moves; set "in": {fz:.1f} on this shot if it shows')
    plays = s["end"] - s["start"] if all(isinstance(s.get(k), (int, float)) for k in ("start", "end")) else 0
    start_in = s.get("in", s.get("start", 0) if s.get("type") in ("avatar", "footage") else 0)
    left = (d - start_in) / s.get("speed", 1) if isinstance(start_in, (int, float)) else d
    if plays - left > 0.25 and not s.get("freeze_ok"):
        flags.append(f'{s["id"]}: the clip has {max(left, 0):.1f}s from "in" {start_in} but the shot is {plays:.1f}s: '
                     f'the last {plays - max(left, 0):.1f}s would freeze. Set a smaller "in", shorten the shot or '
                     "make a longer clip")
    rows.append((s, frames, d, plays))

unknown = [i for i in a.only or [] if i not in {s["id"] for s in shots}]
if unknown:
    print(f"  no shot called {', '.join(unknown)} in {a.shots}")
if not rows:
    sys.exit("No clips to show." + (f" No clip yet for {', '.join(missing)}: make them (generate.py clips .) first."
                                    if missing else " Only clip, talking, library and avatar shots have clips."))

base = "contact_sheet" if a.shots == "shots.json" else "contact_sheet_" + os.path.basename(a.shots).replace(".json", "")
for f in os.listdir(qc):        # pages left by an earlier, longer sheet would be mistaken for this one
    if re.fullmatch(re.escape(base) + r"(_\d+)?\.jpg", f):
        os.remove(os.path.join(qc, f))
# Each clip is a block (3 frames, its id and line under them), laid left to right, a new line when one is
# full, a new page when one is full (PER_PAGE clips, or PAGE_H tall), so a page stays readable at any count.
pages, page, x, y, line_h, width = [], [], GAP, GAP, 0, 0
for row in rows:
    frames = row[1]
    bw, bh = sum(im.width for im in frames) + 2 * GAP, max(im.height for im in frames) + LABEL
    if page and x + bw > PAGE_W:
        x, y, line_h = GAP, y + line_h + 2 * GAP, 0
    if page and (len(page) == PER_PAGE or y + bh > PAGE_H):
        pages.append((page, width, y + line_h + GAP if x > GAP else y))
        page, x, y, line_h, width = [], GAP, GAP, 0, 0
    page.append(((x, y), row))
    x += bw + 3 * GAP
    line_h = max(line_h, bh)
    width = max(width, x)
pages.append((page, width, y + line_h + GAP))
saved = []
for p, (page, width, height) in enumerate(pages, 1):
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    for (x, y), (s, frames, d, plays) in page:
        fx, fh = x, max(im.height for im in frames)
        for im in frames:
            sheet.paste(im, (fx, y + (fh - im.height) // 2))
            fx += im.width + GAP
        when = f'{mmss(s["start"])}-{mmss(s["end"])}, {plays:.1f}s shot, ' if plays else ""
        draw.text((x, y + fh + 4), f'{s["id"]}  ({when}{d:.1f}s clip)', fill="black", font=font)
        draw.multiline_text((x, y + fh + 34), "\n".join(wrap(str(s.get("text", "")), fx - x - GAP)[:2]),
                            fill="#444", font=small, spacing=4)
    out = os.path.join(qc, f"{base}.jpg" if len(pages) == 1 else f"{base}_{p}.jpg")
    sheet.save(out, quality=85)
    saved.append(out)
for out in saved:
    print("saved", out)
print(f"{len(rows)} clips on {len(pages)} page{'s' if len(pages) > 1 else ''}"
      + (": look at every page" if len(pages) > 1 else ""))
for i in missing:
    print(f"  no clip yet for {i} (make it: generate.py clips . --only {i})")
for f in flags:
    print("  CHECK:", f)
