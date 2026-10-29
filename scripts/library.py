"""The user's own clip library (UGC mode and mixed mode).

    library.py index <folder>                 look at every clip once: length, shape, 4 frames each
    library.py sheet <folder> [--page 1]      one image of 12 clips x 4 frames, for Claude to look at and tag
    library.py tag <folder> <clip> "<tags>"   save what's in a clip (who, action, place, mood, product shown)
    library.py find <folder> "<words>"        best clips for a line, from file names and tags
    library.py used <folder> <clip> <project> mark a clip as used (so later ads can avoid repeats)

The index lives in <folder>/_index/index.json and is updated, never rebuilt: new clips are added,
tags you wrote are kept. Frames are in <folder>/_index/frames/.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import duration, ffmpeg, load_font, run_ffmpeg

VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
PER_PAGE = 12


def paths(folder):
    idx = os.path.join(folder, "_index")
    return idx, os.path.join(idx, "index.json"), os.path.join(idx, "frames")


def load(folder):
    _, ip, _ = paths(folder)
    if os.path.exists(ip):
        with open(ip) as f:
            return json.load(f)
    return {"clips": {}}


def save(folder, data):
    idx, ip, _ = paths(folder)
    os.makedirs(idx, exist_ok=True)
    with open(ip, "w") as f:
        json.dump(data, f, indent=1)


def size_of(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", r)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    if re.search(r"rotate\s*:\s*-?90|displaymatrix: rotation of -?90", r):
        w, h = h, w
    return w, h


def cmd_index(a):
    data = load(a.folder)
    _, _, fr = paths(a.folder)
    os.makedirs(fr, exist_ok=True)
    files = sorted(f for f in os.listdir(a.folder) if f.lower().endswith(VIDEO))
    new = 0
    for f in files:
        if f in data["clips"]:
            continue
        p = os.path.join(a.folder, f)
        d = duration(p)
        w, h = size_of(p)
        frames = []
        for k in range(4):
            t = d * (k + 0.5) / 4
            out = os.path.join(fr, f"{os.path.splitext(f)[0]}_{k + 1}.jpg")
            run_ffmpeg(["-ss", f"{t:.2f}", "-i", p, "-frames:v", "1", "-vf", "scale=-2:320", out])
            frames.append({"t": round(t, 2), "file": os.path.relpath(out, a.folder)})
        data["clips"][f] = {"seconds": round(d, 2), "w": w, "h": h,
                            "shape": "vertical" if h > w else ("square" if h == w else "horizontal"),
                            "frames": frames, "tags": "", "used_in": []}
        new += 1
        print(f"  {f}  {d:.1f}s  {w}x{h}")
    gone = [f for f in data["clips"] if f not in files]
    for f in gone:
        del data["clips"][f]
    save(a.folder, data)
    untagged = sum(1 for c in data["clips"].values() if not c["tags"])
    pages = (len(data["clips"]) + PER_PAGE - 1) // PER_PAGE
    print(f"{len(data['clips'])} clips ({new} new, {len(gone)} removed). {untagged} still need tags. "
          f"Look at them with: library.py sheet <folder> --page 1..{pages}")


def cmd_sheet(a):
    from PIL import Image, ImageDraw
    data = load(a.folder)
    names = sorted(data["clips"])
    page = names[(a.page - 1) * PER_PAGE:a.page * PER_PAGE]
    if not page:
        sys.exit("No clips on that page.")
    font = load_font(20)
    rows = []
    for n in page:
        c = data["clips"][n]
        ims = [Image.open(os.path.join(a.folder, fr["file"])).convert("RGB") for fr in c["frames"]]
        ims = [im.resize((int(im.width * 240 / im.height), 240)) for im in ims]
        w = 300 + sum(im.width + 8 for im in ims)
        row = Image.new("RGB", (w, 250), "white")
        d = ImageDraw.Draw(row)
        d.text((8, 8), n[:28], fill="black", font=font)
        d.text((8, 40), f'{c["seconds"]}s {c["shape"]}', fill="#555", font=font)
        if c["tags"]:
            d.multiline_text((8, 72), "\n".join(re.findall(".{1,26}(?:\\s|$)", c["tags"])[:6]), fill="#226", font=font)
        x = 300
        for im in ims:
            row.paste(im, (x, 5))
            x += im.width + 8
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), 250 * len(rows)), "white")
    for i, r in enumerate(rows):
        sheet.paste(r, (0, i * 250))
    idx, _, _ = paths(a.folder)
    out = os.path.join(idx, f"sheet_{a.page}.jpg")
    sheet.save(out, quality=80)
    print("saved", out, f"({len(page)} clips; frames are at 1/8, 3/8, 5/8 and 7/8 of each clip)")


def cmd_tag(a):
    data = load(a.folder)
    if a.clip not in data["clips"]:
        sys.exit(f"Not in the index: {a.clip}")
    data["clips"][a.clip]["tags"] = a.tags
    save(a.folder, data)
    print("tagged", a.clip)


def words(text):
    return set(re.findall(r"[a-z]+", text.lower().replace("_", " ")))


def cmd_find(a):
    data = load(a.folder)
    q = words(a.words) - {"the", "a", "and", "my", "i", "to", "of", "in", "on", "it", "was", "her", "his", "is"}
    scored = []
    for n, c in data["clips"].items():
        name = " ".join(re.findall("[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", n).lower()))
        hay = words(name + " " + c["tags"])
        hits = sum(1 for w in q if any(h.startswith(w[:5]) for h in hay))
        if hits:
            scored.append((hits - 0.5 * len(c["used_in"]) / 5, n, c))
    scored.sort(reverse=True)
    for s, n, c in scored[:a.top]:
        used = f'  used {len(c["used_in"])}x' if c["used_in"] else ""
        print(f"{s:4.1f}  {n}  {c['seconds']}s  {c['tags'][:70]}{used}")
    if not scored:
        print("No match in names or tags. Tag more clips, or this line is a gap (mixed mode: make it with AI).")


def cmd_used(a):
    data = load(a.folder)
    c = data["clips"].get(a.clip)
    if not c:
        sys.exit(f"Not in the index: {a.clip}")
    c["used_in"].append({"project": a.project, "date": datetime.date.today().isoformat()})
    save(a.folder, data)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
i = sub.add_parser("index"); i.add_argument("folder")
s = sub.add_parser("sheet"); s.add_argument("folder"); s.add_argument("--page", type=int, default=1)
t = sub.add_parser("tag"); t.add_argument("folder"); t.add_argument("clip"); t.add_argument("tags")
f = sub.add_parser("find"); f.add_argument("folder"); f.add_argument("words"); f.add_argument("--top", type=int, default=5)
u = sub.add_parser("used"); u.add_argument("folder"); u.add_argument("clip"); u.add_argument("project")
a = ap.parse_args()
{"index": cmd_index, "sheet": cmd_sheet, "tag": cmd_tag, "find": cmd_find, "used": cmd_used}[a.cmd](a)
