"""Other sizes from a finished 9:16 ad.

    variants.py <project> [--sizes 4x5 1x1 16x9] [--files final/x_9x16_v1.mp4 ...]

4x5 (1080x1350) and 1x1 (1080x1080) are centre crops: the 4:5 safe zone in every frame keeps faces,
products and captions inside them. 16x9 (1920x1080) puts the 9:16 picture in the middle over a
blurred, darkened copy of itself. Default files: every *_9x16_*.mp4 in final/ (not previews).
Output names swap 9x16 for the size, e.g. ad_hookA_4x5_v1.mp4. Sound is copied untouched.
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import run_ffmpeg

SIZES = {
    "4x5": "crop=1080:1350:0:(ih-1350)/2,setsar=1",
    "1x1": "crop=1080:1080:0:(ih-1080)/2,setsar=1",
    "16x9": ("split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
             "boxblur=30:5,eq=brightness=-0.12[bg];[b]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1"),
}

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--sizes", nargs="+", default=["4x5"], choices=sorted(SIZES))
ap.add_argument("--files", nargs="*")
a = ap.parse_args()

files = [os.path.join(a.project, f) for f in a.files] if a.files else \
    sorted(f for f in glob.glob(os.path.join(a.project, "final", "*_9x16_*.mp4")))
if not files:
    sys.exit("No 9:16 finals found in final/. Run edit.py first.")
for src in files:
    for size in a.sizes:
        out = src.replace("_9x16_", f"_{size}_") if "_9x16_" in src else src.replace(".mp4", f"_{size}.mp4")
        run_ffmpeg(["-i", src, "-filter_complex", f"[0:v]{SIZES[size]}[v]", "-map", "[v]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-movflags", "+faststart", out])
        print("saved", out)
