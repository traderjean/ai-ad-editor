"""Other sizes from a finished 9:16 ad.

    variants.py <project> [--sizes 4x5 1x1 16x9] [--files final/x_9x16_v1.mp4 ...] [--redo]

4x5 (1080x1350) and 1x1 (1080x1080) are centre crops. 4x5 keeps 15%-85% of the height, so the 4:5 safe
zone in every frame keeps faces, products and captions inside it. 1x1 keeps only the middle 22%-78%:
anything above or below that (a low caption, on-screen text, a product at the bottom) is cut, so check
the 1x1 files by eye. 16x9 (1920x1080) puts the 9:16 picture in the middle over a
blurred, darkened copy of itself. Default files: the newest take (_v<n>) of each *_9x16_*.mp4 in final/, as
qc.py checks; --files makes sizes of others. A size already made from the same 9:16 is kept (--redo makes it
again). Output names swap 9x16 for the size, e.g. ad_hookA_4x5_v1.mp4. Sound is copied untouched.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import duration, ffmpeg, run_ffmpeg

SIZES = {
    "4x5": "crop=1080:1350:0:(ih-1350)/2,setsar=1",
    "1x1": "crop=1080:1080:0:(ih-1080)/2,setsar=1",
    "16x9": ("split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
             "boxblur=30:5,eq=brightness=-0.12[bg];[b]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1"),
}

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--sizes", nargs="+", default=["4x5"], choices=sorted(SIZES))
ap.add_argument("--files", nargs="*", help="these 9:16 files instead of the newest take of each")
ap.add_argument("--redo", action="store_true", help="make a size again even if it was already made from this 9:16")
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
    newest, older = {}, []      # older _v<n> takes stay in final/ for history: sizes are made of the newest
    for f in sorted(glob.glob(os.path.join(glob.escape(a.project), "final", "*_9x16_*.mp4"))):
        if os.path.basename(f).startswith("preview_"):
            continue
        m = re.match(r"(.*)_v(\d+)\.mp4$", os.path.basename(f))
        key, n = (m.group(1), int(m.group(2))) if m else (f, 0)
        if key in newest:
            older.append(min(newest[key], (n, f))[1])
        if key not in newest or n > newest[key][0]:
            newest[key] = (n, f)
    files = sorted(f for _, f in newest.values())
    if older:
        print("skipping older takes:", ", ".join(os.path.basename(f) for f in sorted(older)),
              "(--files makes sizes of one)")
if not files:
    sys.exit("No 9:16 finals found in final/. Run edit.py first.")


def size_of(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stderr
    v = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", r)
    return (int(v.group(1)), int(v.group(2))) if v else None


failed = []
for src in files:
    wh = size_of(src)
    if wh != (1080, 1920):
        failed.append(f"{src} is {'%dx%d' % wh if wh else 'not a video ffmpeg can read'}, not a 1080x1920 9:16 "
                      "final: give one edit.py made (not a preview), or run edit.py again if it was cut off.")
        continue
    for size in a.sizes:
        folder, name = os.path.split(src)
        root, ext = os.path.splitext(name)
        out = os.path.join(folder, name.replace("_9x16_", f"_{size}_") if "_9x16_" in name else f"{root}_{size}{ext}")
        if not a.redo and os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
            print("kept", out, "(already made from this 9:16; --redo makes it again)")
            continue
        part = out + ".part"        # written aside and renamed when done: a stopped run never leaves half a file
        try:
            run_ffmpeg(["-i", src, "-filter_complex", f"[0:v]{SIZES[size]}[v]", "-map", "[v]", "-map", "0:a",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", "-f", "mp4", part])
            got, want = duration(part), duration(src)
            if abs(got - want) > 0.5:       # ffmpeg reads a cut-off file as far as it goes, without an error
                raise SystemExit(f"it came out {got:.1f}s long but {os.path.basename(src)} says {want:.1f}s")
        except SystemExit as e:
            if os.path.exists(part):
                os.remove(part)
            failed.append(f"{out} not made: {str(e.code).strip().splitlines()[-1]}. Check that {src} plays "
                          "(qc.py checks it); if it was cut off, run edit.py again.")
            continue
        os.replace(part, out)
        print("saved", out)
if "1x1" in a.sizes:
    print("1x1 keeps only the middle 22%-78% of the height: look at it for cut-off captions, text, products or faces.")
if failed:
    sys.exit("\n".join(failed))
