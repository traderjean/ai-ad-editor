"""Shared helpers: settings (providers.json), JSON files, ffmpeg, durations, project files, spend log and budget."""
import csv
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):    # a Windows console (cp1252) can't show every character: never crash on one
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

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

def load_json(path, fix=""):
    """A JSON file. A missing or broken one stops with its name (and the line), not a traceback."""
    try:
        with open(path, encoding="utf-8-sig") as f:      # -sig: Notepad's byte-order mark is fine
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"{path} doesn't exist. {fix}".strip())
    except (ValueError, UnicodeDecodeError) as e:
        where = f" (line {e.lineno}: {e.msg})" if isinstance(e, json.JSONDecodeError) else ""
        sys.exit(f"{path} is not valid JSON{where}. {fix}".strip())


def read_text(path):
    """A text file the user may have saved anywhere (a script, a prompt): UTF-8 with or without Notepad's
    byte-order mark, UTF-16 (Notepad's "Unicode"), else Windows-1252 (an older "ANSI" save of a French or
    German script) with a note to check its accents."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        print(f"NOTE {path} isn't UTF-8 (read as Windows-1252): check its accents, or save it as UTF-8 and run "
              f"this again.")
        return raw.decode("cp1252", errors="replace")


def load_settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if os.path.exists(SETTINGS):
        saved = load_json(SETTINGS, "Fix it, or delete it and run check_setup.py again.")
        if not isinstance(saved, dict):
            sys.exit(f"{SETTINGS} is not a settings file. Delete it and run check_setup.py again.")
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k].update(v)
            else:
                s[k] = v
    return s


def save_settings(s):
    with open(SETTINGS, "w", encoding="utf-8") as f:
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


FFMPEG_ENCODERS = ("libx264", "aac")
FFMPEG_FILTERS = ("ass", "loudnorm", "sidechaincompress", "zoompan", "freezedetect", "blackdetect", "tpad", "boxblur")


def ffmpeg_fix(exe=None):
    return (f"Your ffmpeg ({exe or ffmpeg()}) is a cut-down build. Install the full one: pip3 install imageio-ffmpeg "
            f"(then take the other ffmpeg off your PATH) or brew install ffmpeg, and run check_setup.py again.")


def run_ffmpeg(args):
    exe = ffmpeg()
    if not exe:
        sys.exit("ffmpeg not found. Install it (see check_setup.py) and try again.")
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        hint = "\n" + ffmpeg_fix(exe) if "Unknown encoder" in r.stderr or "No such filter" in r.stderr else ""
        sys.exit("ffmpeg failed:\n" + r.stderr[-2000:] + hint)


def duration(path):
    """Length of an audio or video file in seconds (no ffprobe needed)."""
    exe = ffmpeg()
    if not exe:
        sys.exit("ffmpeg not found. Install it (see check_setup.py) and try again.")
    r = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        sys.exit(f"Could not read the length of {path}")
    h, mi, se = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(se)


ABBREVIATIONS = {"a.m.", "p.m.", "dr.", "mr.", "mrs.", "ms.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.", "approx.",
                 "mme.", "mlle.", "env.", "p.ex."}


def sentence_end(word):
    """True when a word ends a sentence: "?", "!" or "…", or a full stop that isn't an abbreviation ("a.m.", "Dr.",
    "M.", "U.S."). Closing quotes and brackets are looked past ("encore ?»")."""
    w = str(word).rstrip("\"'”’»)]").rstrip()
    if w.endswith(("?", "!", "…")):
        return True
    return w.endswith(".") and w.lower() not in ABBREVIATIONS and not re.search(r"\w\.\w", w) \
        and not re.fullmatch(r"\w\.", w)


def load_audio(path, rate=16000):
    """Mono float32 samples for faster-whisper, decoded with our own ffmpeg. Passing a file path makes
    faster-whisper decode with PyAV, whose newer releases break it ("unexpected keyword 'metadata_errors'")."""
    import numpy as np
    r = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path,
                        "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"], capture_output=True)
    if r.returncode != 0:
        sys.exit(f"Could not read the audio in {path}:\n" + r.stderr.decode(errors="replace")[-1000:])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768


def mmss(seconds):
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


# ---------- project files ----------

CLIP_TYPES = ("clip", "veo", "talking")      # shot types made by the video slot ("veo" = old name for "clip")
PROJECT_FILES = ("state.json", "shots.json", "budget.json", "brief.md")


def find_project(path=None):
    """The project folder a file belongs to: the nearest folder above it with state.json, shots.json,
    budget.json or brief.md (never above the working folder when the file is inside it), else the
    working folder (scripts are run from inside the project)."""
    cwd = os.getcwd()
    if path:
        d = os.path.dirname(os.path.abspath(path))
        inside = d == cwd or d.startswith(os.path.join(cwd, ""))
        for _ in range(64 if inside else 4):
            if any(os.path.exists(os.path.join(d, f)) for f in PROJECT_FILES):
                return d
            if (inside and d == cwd) or os.path.dirname(d) == d:
                break
            d = os.path.dirname(d)
    return cwd


def rel(path, start):
    """`path` as seen from `start` for messages; the full path when it's on another drive (Windows)."""
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return path


def voiceover_file(project, data):
    """The voiceover a plan is cut to: its "vo", else the first avatar shot's video (an AI avatar video is the
    voiceover as well as the picture). None when there is neither."""
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    rel = data.get("vo") or next((s["source"] for s in shots
                                  if isinstance(s, dict) and s.get("type") == "avatar" and s.get("source")), None)
    return os.path.join(project, rel) if rel else None


def clip_path(project, shot):
    """The video file a shot plays: its "clip" override (e.g. a lip-synced take), else clips/<id>.mp4,
    else its "source" for an AI talking-avatar video. None for stills and text cards, and for a library or
    avatar shot with no "source" yet."""
    kind = shot.get("type", "clip")
    if shot.get("clip"):
        return os.path.join(project, shot["clip"])
    if kind in CLIP_TYPES:
        return os.path.join(project, "clips", shot["id"] + ".mp4")
    if kind in ("avatar", "footage", "library"):   # "footage" = old name; "library" = a clip from the user's library
        if not shot.get("source"):
            return None
        path = os.path.join(project, shot["source"])
        if kind == "library" and not os.path.exists(path) and os.path.exists(shot["source"]):
            return shot["source"]       # "<folder>/<clip>", the folder as given to library.py (from the working folder)
        return path
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

BUDGET_FILE = "budget.json"     # {"budget": 15} in the project folder, written by check_setup.py --budget


def project_name(project=None):
    """The name spend_log.csv files a project under: its folder's name (the working folder by default)."""
    return os.path.basename(os.path.abspath(project)) if project else os.path.basename(os.getcwd())


def load_budget(project=None):
    """The ad's budget in USD from <project>/budget.json, or None if none is set."""
    path = os.path.join(project or os.getcwd(), BUDGET_FILE)
    if not os.path.exists(path):
        return None
    b = load_json(path, "Set it again with: check_setup.py --budget <usd> (run inside the project).")
    b = b.get("budget") if isinstance(b, dict) else None
    if not isinstance(b, (int, float)) or isinstance(b, bool) or b < 0:
        sys.exit(f"{path} should hold {{\"budget\": <usd>}}. Set it again with: check_setup.py --budget <usd>")
    return float(b) or None


def spend_rows():
    """Every row of spend_log.csv as a dict (time, what, usd, project); [] when nothing was spent yet."""
    if not os.path.exists(SPEND_LOG):
        return []
    with open(SPEND_LOG, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if r.get("what")]


def spent(project=None):
    """(USD spent on this project's runs of known cost, number of its runs of unknown cost)."""
    name, usd, unknown = project_name(project), 0.0, 0
    for r in spend_rows():
        if (r.get("project") or "") != name:
            continue
        try:
            usd += float(r["usd"])
        except (TypeError, ValueError):
            unknown += 1
    return usd, unknown


def check_spend(estimate, project=None):
    """Block a run over the user's own per-run limit, or one that would take the ad past its budget
    (budget.json in the project folder), if they set them. Unknown cost = no block."""
    limit = load_settings().get("spend_limit_per_run")
    if limit and estimate and estimate > limit:
        sys.exit(f"BLOCKED: this run (~${estimate:.2f}) is over your ${limit:.2f} per-run limit "
                 f"(spend_limit_per_run in providers.json). Split it up or raise the limit yourself.")
    budget = load_budget(project)
    if not budget:
        return
    done, unknown = spent(project)
    now = estimate or 0
    also = f" ({unknown} earlier run(s) of unknown cost aren't counted)" if unknown else ""
    if now > 0 and done + now > budget + 1e-9:      # collecting an already-paid job ($0) always goes through
        sys.exit(f"BLOCKED: this ad has spent ${done:.2f} and this run (~${now:.2f}) would take it to "
                 f"${done + now:.2f}, over its ${budget:.2f} budget{also}. Ask the user: raise it with "
                 f"check_setup.py --budget <usd> (run inside the project), or make less.")
    if estimate is None:
        print(f"This ad: ${done:.2f} spent of your ${budget:.2f} budget; this run's cost is unknown{also}")
    else:
        print(f"This ad: ${done:.2f} spent + ${now:.2f} now = ${done + now:.2f} of your ${budget:.2f} budget{also}")


def log_spend(what, amount, project=None):
    """One row per paid job; a job of unknown cost gets a row too, with usd left empty."""
    new = not os.path.exists(SPEND_LOG)
    with open(SPEND_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")     # quotes a field with a comma in it (a label, a project path)
        if new:
            w.writerow(["time", "what", "usd", "project"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), what,
                    "" if amount is None else f"{amount:.3f}", project_name(project)])
