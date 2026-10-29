"""Shared helpers: settings (providers.json), ffmpeg, durations, spend log."""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(SKILL_DIR, "providers.json")
SPEND_LOG = os.path.join(SKILL_DIR, "spend_log.csv")

SLOTS = ("image", "video", "voice", "music", "lipsync")
QUALITIES = ("draft", "standard", "best")
W, H = 1080, 1920

DEFAULT_SETTINGS = {
    "image": {"mode": "none"},
    "video": {"mode": "none", "max_seconds": 8},
    "voice": {"mode": "none"},
    "music": {"mode": "none"},
    "lipsync": {"mode": "none"},
    "spend_limit_per_run": None,
}


# ---------- settings ----------

def load_settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as f:
            saved = json.load(f)
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k].update(v)
            else:
                s[k] = v
    return s


def save_settings(s):
    with open(SETTINGS, "w") as f:
        json.dump(s, f, indent=2)
        f.write("\n")


# ---------- ffmpeg ----------

def ffmpeg():
    """ffmpeg on PATH, else the imageio-ffmpeg bundle (pip install imageio-ffmpeg)."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def run_ffmpeg(args):
    exe = ffmpeg()
    if not exe:
        sys.exit("ffmpeg not found. Install it (see check_setup.py) and try again.")
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + r.stderr[-2000:])


def duration(path):
    """Length of an audio or video file in seconds (no ffprobe needed)."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        sys.exit(f"Could not read the length of {path}")
    h, mi, se = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(se)


def mmss(seconds):
    return f"{int(seconds // 60)}:{int(round(seconds % 60)):02d}"


# ---------- project files ----------

CLIP_TYPES = ("clip", "veo", "talking")      # shot types made by the video slot ("veo" = old name for "clip")


def clip_path(project, shot):
    """The video file a shot plays: its "clip" override (e.g. a lip-synced take), else clips/<id>.mp4,
    else its "source" for an AI talking-avatar video. None for stills and text cards."""
    kind = shot.get("type", "clip")
    if shot.get("clip"):
        return os.path.join(project, shot["clip"])
    if kind in CLIP_TYPES:
        return os.path.join(project, "clips", shot["id"] + ".mp4")
    if kind in ("avatar", "footage", "library"):   # "footage" = old name; "library" = a clip from the user's library
        return os.path.join(project, shot["source"])
    return None


# Bold fonts to try, in order, on macOS / Windows / Linux. The first one found is used for captions.
FONT_FILES = [
    ("Arial Black", "/System/Library/Fonts/Supplemental/Arial Black.ttf"),
    ("Arial Black", "C:/Windows/Fonts/ariblk.ttf"),
    ("Arial", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("Arial", "C:/Windows/Fonts/arialbd.ttf"),
    ("DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("Liberation Sans", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("Helvetica", "/System/Library/Fonts/Helvetica.ttc"),
]


def find_font(name=None, path=None):
    """(font name, font file) for captions: the one asked for if it exists, else the first bold font found."""
    if path and os.path.exists(path):
        return name or os.path.splitext(os.path.basename(path))[0], path
    for n, p in FONT_FILES:
        if (not name or n == name) and os.path.exists(p):
            return n, p
    for n, p in FONT_FILES:
        if os.path.exists(p):
            return n, p
    return name or "Arial", None


def load_font(size, name=None, path=None):
    from PIL import ImageFont
    _, p = find_font(name, path)
    try:
        return ImageFont.truetype(p, size) if p else ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


# ---------- spend ----------

def check_spend(estimate):
    """Block a run over the user's own per-run limit (if they set one). Unknown cost = no block."""
    limit = load_settings().get("spend_limit_per_run")
    if limit and estimate and estimate > limit:
        sys.exit(f"BLOCKED: this run (~${estimate:.2f}) is over your ${limit:.2f} per-run limit "
                 f"(spend_limit_per_run in providers.json). Split it up or raise the limit yourself.")


def log_spend(what, amount, project=""):
    if amount is None:
        return
    new = not os.path.exists(SPEND_LOG)
    with open(SPEND_LOG, "a") as f:
        if new:
            f.write("time,what,usd,project\n")
        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')},{what},{amount:.3f},{project}\n")
