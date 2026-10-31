"""The user's own clip library (UGC mode and mixed mode).

    library.py index <folder>                 look at every clip once: length, shape, 4 frames each
    library.py sheet <folder> [--page 1]      one image of 12 clips x 4 frames, for Claude to look at and tag
    library.py tag <folder> <clip> "<tags>"   save what's in a clip (who, action, place, mood, product shown)
    library.py tag <folder> --file tags.tsv   tag many clips at once: one "<clip><TAB><tags>" per line
    library.py list <folder> [--untagged] [--unused]   every clip on one line: length, shape, used, tags
    library.py find <folder> "<words>" [--avoid-used]  best clips for a line, from file names and tags
    library.py used <folder> <clip>... [--project <name>]  mark clips as used in an ad (default: this folder's name)

The index lives in <folder>/_index/index.json and is updated, never rebuilt: new clips are added,
tags you wrote are kept. Clips in subfolders are indexed too, named by their path ("2024/walk.mp4").
Frames are in <folder>/_index/frames/ (index makes deleted ones again). Files that can't be read (empty,
still copying, no picture) are skipped and listed; index again once they're fixed. HDR phone clips
(HLG/PQ) are flagged: their colours look flat in the ad unless converted first (index prints the command).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import duration, ffmpeg, load_font, load_json, project_name, run_ffmpeg

VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
PER_PAGE = 12


def paths(folder):
    idx = os.path.join(folder, "_index")
    return idx, os.path.join(idx, "index.json"), os.path.join(idx, "frames")


def load(folder):
    _, ip, _ = paths(folder)
    if os.path.exists(ip):     # a broken one stops with its line, never a traceback
        data = load_json(ip, "Fix that line and run this again (don't delete the file: the tags in it are your work).")
        if isinstance(data, dict) and isinstance(data.get("clips"), dict):
            for n, c in data["clips"].items():      # a hand-edited entry: fill in what's missing, never a KeyError
                if not isinstance(c, dict):
                    sys.exit(f'{ip}: the entry for {n} isn\'t {{...}}. Fix it (or delete that entry and index again).')
                if not isinstance(c.get("tags"), str):
                    c["tags"] = ""
                if not isinstance(c.get("used_in"), list):
                    c["used_in"] = []
                c["used_in"] = [u for u in c["used_in"] if isinstance(u, dict)]
                c.setdefault("seconds", 0)
                c.setdefault("shape", "?")
                c.setdefault("frames", [])
            return data
        sys.exit(f'{ip} isn\'t a library index (it should hold {{"clips": {{...}}}}). Move it away and index again.')
    return {"clips": {}}


def save(folder, data):
    idx, ip, _ = paths(folder)
    os.makedirs(idx, exist_ok=True)
    with open(ip + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(ip + ".tmp", ip)     # never a half-written index: the tags in it are hand work


def size_of(path):
    """(width, height, HDR kind or None) as the clip shows: a phone clip turned 90 degrees swaps them."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stderr
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", r)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    if re.search(r"rotate\s*:\s*-?90|displaymatrix: rotation of -?90", r):
        w, h = h, w
    v = re.search(r"Video:.*", r)
    v = v.group(0) if v else ""
    hdr = "HLG" if "arib-std-b67" in v else "PQ" if "smpte2084" in v else "wide colour" if "bt2020" in v else None
    return w, h, hdr


# HLG/PQ: tone-map to SDR. Wide colour only (bt2020, SDR brightness): just map the colours to bt709.
HDR_FIX = ("ffmpeg -i {i} -vf zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p -c:a copy {o}")
WIDE_FIX = "ffmpeg -i {i} -vf zscale=p=bt709:t=bt709:m=bt709:r=tv,format=yuv420p -c:a copy {o}"


def hdr_label(kind):
    return "wide-colour (bt2020)" if kind == "wide colour" else f"HDR ({kind})"


def quote(path):
    return f'"{path}"' if " " in path else path


def video_files(folder):
    """Every clip in the folder and its subfolders, as "<subfolder>/<name>" ("/" on every system).
    Not _index, hidden folders, or "._clip.mp4" files (macOS copy leftovers, not clips)."""
    found = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "_index" and not d.startswith("."))
        for n in names:
            if n.lower().endswith(VIDEO) and not n.startswith("._"):
                found.append(os.path.relpath(os.path.join(root, n), folder).replace(os.sep, "/"))
    return sorted(found)


def make_frames(folder, f, d):
    """4 frames of a clip, at 1/8, 3/8, 5/8 and 7/8 of it."""
    _, _, fr = paths(folder)
    frames = []
    for k in range(4):
        t = d * (k + 0.5) / 4
        # full name: clip.mov and clip.mp4 don't share frames; a subfolder's "/" can't be in a file name
        out = os.path.join(fr, f"{f.replace('/', '__')}_{k + 1}.jpg")
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", os.path.join(folder, f), "-frames:v", "1", "-vf", "scale=-2:320", out])
        frames.append({"t": round(t, 2), "file": os.path.relpath(out, folder)})
    return frames


def frames_missing(folder, c):
    return not isinstance(c["frames"], list) or not c["frames"] or any(
        not isinstance(x, dict) or not os.path.isfile(os.path.join(folder, str(x.get("file", "")))) for x in c["frames"])


def cmd_index(a):
    if not os.path.isdir(a.folder):
        sys.exit(f"{a.folder} isn't a folder. Give the library folder's full path.")
    data = load(a.folder)
    _, _, fr = paths(a.folder)
    os.makedirs(fr, exist_ok=True)
    files = video_files(a.folder)
    new, skipped, hdr, remade = 0, [], [], 0
    try:
        for f in files:
            if f in data["clips"]:
                c = data["clips"][f]
                if "hdr" not in c:      # indexed before HDR was checked: look once
                    c["hdr"] = size_of(os.path.join(a.folder, f))[2]
                if c["hdr"]:
                    hdr.append(f)
                if frames_missing(a.folder, c):     # frames deleted: make them again, the tags stay
                    try:
                        c["frames"] = make_frames(a.folder, f, duration(os.path.join(a.folder, f)))
                        remade += 1
                    except SystemExit:
                        skipped.append(f)
                continue
            p = os.path.join(a.folder, f)
            try:        # duration() and run_ffmpeg() exit on a file they can't read: skip it, keep going
                d = duration(p)
                w, h, kind = size_of(p)
                frames = make_frames(a.folder, f, d)
            except SystemExit:
                skipped.append(f)
                continue
            data["clips"][f] = {"seconds": round(d, 2), "w": w, "h": h,
                                "shape": "vertical" if h > w else ("square" if h == w else "horizontal"),
                                "frames": frames, "tags": "", "used_in": [], "hdr": kind}
            new += 1
            if kind:
                hdr.append(f)
            print(f"  {f}  {d:.1f}s  {w}x{h}" + (f"  {hdr_label(kind)}" if kind else ""))
    finally:            # even if stopped part way, the clips done so far are kept
        gone = [f for f in data["clips"] if f not in files]
        for f in gone:
            del data["clips"][f]
        save(a.folder, data)
    for f in skipped:
        print(f"  skipped {f}: can't be read (empty, still copying, or no picture)")
    for f in hdr:
        print(f"  {f}: {hdr_label(data['clips'][f]['hdr'])} clip, its colours will look flat in the ad unless it is "
              "converted first")
    if hdr:     # one command per clip, so each can be copied as it is
        print("Convert each one (needs an ffmpeg with zscale: the imageio-ffmpeg and Homebrew ones have it), move "
              "the original out of the library folder, then index again:")
        for f in hdr:
            fix = WIDE_FIX if data["clips"][f]["hdr"] == "wide colour" else HDR_FIX
            print("  " + fix.format(i=quote(os.path.join(a.folder, f)),
                                    o=quote(os.path.join(a.folder, os.path.splitext(f)[0] + "_sdr.mp4"))))
    untagged = sum(1 for c in data["clips"].values() if not c["tags"])
    pages = (len(data["clips"]) + PER_PAGE - 1) // PER_PAGE
    if remade:
        print(f"  made the frames of {remade} clip(s) again (they were missing)")
    print(f"{len(data['clips'])} clips ({new} new, {len(gone)} removed, {len(skipped)} skipped). {untagged} still need "
          f"tags. Look at them with: library.py sheet <folder> --page 1..{pages}")


def cmd_sheet(a):
    from PIL import Image, ImageDraw
    data = load(a.folder)
    names = sorted(data["clips"])
    page = names[(a.page - 1) * PER_PAGE:a.page * PER_PAGE]
    if not page:
        sys.exit("No clips on that page.")
    font = load_font(20)
    rows = []
    lost = [n for n in page if frames_missing(a.folder, data["clips"][n])]
    if lost:        # deleted or never made: index makes them again, keeping the tags
        sys.exit(f"The frames of {', '.join(lost)} are missing. Run library.py index {a.folder} (it makes them again "
                 "and keeps the tags), then this.")
    for n in page:
        c = data["clips"][n]
        ims = [Image.open(os.path.join(a.folder, fr["file"])).convert("RGB") for fr in c["frames"]]
        ims = [im.resize((int(im.width * 240 / im.height), 240)) for im in ims]
        w = 300 + sum(im.width + 8 for im in ims)
        row = Image.new("RGB", (w, 250), "white")
        d = ImageDraw.Draw(row)
        d.text((8, 8), n[:28], fill="black", font=font)
        d.text((8, 40), f'{c["seconds"]}s {c["shape"]}' + (" HDR" if c.get("hdr") else ""), fill="#555", font=font)
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
    if a.file:
        if a.clip:
            sys.exit("Give either --file or a clip and its tags, not both.")
        try:
            with open(a.file, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError as e:
            sys.exit(f"Can't read {a.file}: {e.strerror}.")
        todo, bad = [], []
        for k, line in enumerate(lines, 1):
            if not line.strip():
                continue
            clip, _, tags = line.partition("\t")
            if not tags:        # spaces instead of the tab: the clip name ends at its extension
                m = re.match(r"(.+?\.(?:mp4|mov|m4v|webm|mkv))\s+(.+)$", line.strip(), re.I)
                clip, tags = m.groups() if m else (line, "")
            clip, tags = clip.strip(), tags.strip()
            if not tags:
                bad.append(f"line {k}: no tags after {clip.strip()} (put a tab between the clip and its tags)")
            elif clip not in data["clips"]:
                bad.append(f"line {k}: {clip} isn't in the index")
            else:
                todo.append((clip, tags))
        if bad:         # nothing saved: fix the file and run it again, so no line is half done
            sys.exit(f"Nothing tagged: {a.file} has {len(bad)} problem(s). Fix them and run this again:\n  "
                     + "\n  ".join(bad) + "\n(One clip per line: <clip name as library.py list shows it><TAB><tags>.)")
        for clip, tags in todo:
            data["clips"][clip]["tags"] = tags
        save(a.folder, data)
        left = sum(1 for c in data["clips"].values() if not c["tags"])
        print(f"tagged {len(todo)} clips" + (f"; {left} still need tags (library.py list <folder> --untagged)"
                                            if left else "; every clip has tags"))
        return
    if not a.clip or a.tags is None:
        sys.exit('Give a clip and its tags (library.py tag <folder> <clip> "<tags>"), or --file tags.tsv.')
    if a.clip not in data["clips"]:
        sys.exit(f"Not in the index: {a.clip}")
    data["clips"][a.clip]["tags"] = a.tags
    save(a.folder, data)
    print("tagged", a.clip)


def cmd_list(a):
    data = load(a.folder)
    if not data["clips"]:
        sys.exit(f"No clips indexed in {a.folder} yet: run library.py index <folder> first.")
    shown = 0
    for n in sorted(data["clips"]):
        c = data["clips"][n]
        ads = {u.get("project") for u in c["used_in"]}
        if (a.untagged and c["tags"]) or (a.unused and ads):
            continue
        hdr = f" {hdr_label(c['hdr'])}" if c.get("hdr") else ""
        used = f" used {len(ads)}x" if ads else ""
        print(f"{n}  {c['seconds']}s {c['shape']}{hdr}{used}  {c['tags'] or '(no tags)'}")
        shown += 1
    what = " and ".join(w for w, on in (("untagged", a.untagged), ("unused", a.unused)) if on)
    print(f"{shown} of {len(data['clips'])} clips" + (f" are {what}" if what else ""))


def words(text):
    """The words in a text, lower case, accents and digits kept ("3am"); "she's" -> "shes", not "she" + "s"."""
    return set(re.findall(r"[^\W_]+", text.casefold().replace("'", "").replace("\u2019", "")))


def cmd_find(a):
    data = load(a.folder)
    # 1-2 letter words ("m" from "I'm") would match the start of almost any tag
    q = {w for w in words(a.words) if len(w) > 2} - {"the", "and", "was", "her", "his"}
    scored, left_out = [], 0
    for n, c in data["clips"].items():
        name = re.sub(r"([a-z])([A-Z])", r"\1 \2", os.path.splitext(n)[0])    # not the extension: "mov" isn't a tag
        hay = words(name + " " + c["tags"])
        hits = sum(1 for w in q if any(h.startswith(w[:5]) for h in hay))
        ads = len({u.get("project") for u in c["used_in"]})
        if hits and ads and a.avoid_used:
            left_out += 1
        elif hits:      # a point off per earlier ad: a clip seen in 3 ads loses to a fresh one with 2 fewer words
            scored.append((hits - ads, n, c, ads))
    scored.sort(key=lambda x: (-x[0], x[1]))
    for sc, n, c, ads in scored[:a.top]:
        used = f"  used {ads}x" if ads else ""
        hdr = f"  {hdr_label(c['hdr'])}" if c.get("hdr") else ""
        print(f"{sc:4.1f}  {n}  {c['seconds']}s  {c['tags'][:70]}{used}{hdr}")
    if left_out:
        print(f"({left_out} matching clip(s) used in earlier ads left out: run without --avoid-used to see them)"
              if scored else f"The only matches ({left_out}) were used in earlier ads: run without --avoid-used to "
                             "see them, or treat this line as a gap.")
    if not scored and not left_out:
        print("No match in names or tags. Tag more clips, or this line is a gap (mixed mode: make it with AI). "
              "To pick by eye, read every clip's tags with: library.py list <folder>")


def cmd_used(a):
    data = load(a.folder)
    clips, project = list(a.clips), a.project
    if not project and len(clips) >= 2 and clips[-1] not in data["clips"] and not clips[-1].lower().endswith(VIDEO):
        project = clips.pop()       # the old form: used <folder> <clip> <project>
    project = project or project_name()
    missing = [c for c in clips if c not in data["clips"]]
    if missing:
        sys.exit(f"Not in the index: {', '.join(missing)}. Nothing marked: use the names library.py list shows.")
    today = datetime.date.today().isoformat()
    for clip in clips:
        c = data["clips"][clip]
        if any(u.get("project") == project for u in c["used_in"]):      # a revision runs this again: count it once
            print(f"already marked {clip} as used in {project}")
            continue
        c["used_in"].append({"project": project, "date": today})
        print(f"marked {clip} as used in {project}")
    save(a.folder, data)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
i = sub.add_parser("index"); i.add_argument("folder")
s = sub.add_parser("sheet"); s.add_argument("folder"); s.add_argument("--page", type=int, default=1)
t = sub.add_parser("tag"); t.add_argument("folder"); t.add_argument("clip", nargs="?"); t.add_argument("tags", nargs="?")
t.add_argument("--file", help='a text file with one "<clip><TAB><tags>" per line')
ls = sub.add_parser("list"); ls.add_argument("folder")
ls.add_argument("--untagged", action="store_true", help="only clips with no tags yet")
ls.add_argument("--unused", action="store_true", help="only clips no earlier ad used")
f = sub.add_parser("find"); f.add_argument("folder"); f.add_argument("words"); f.add_argument("--top", type=int, default=5)
f.add_argument("--avoid-used", action="store_true", help="leave out clips used in earlier ads")
u = sub.add_parser("used"); u.add_argument("folder"); u.add_argument("clips", nargs="+")
u.add_argument("--project", help="the ad they were used in (default: the working folder's name)")
a = ap.parse_args()
{"index": cmd_index, "sheet": cmd_sheet, "tag": cmd_tag, "list": cmd_list, "find": cmd_find,
 "used": cmd_used}[a.cmd](a)
