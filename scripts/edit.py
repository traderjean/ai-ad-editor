"""Cut the ad: shots on the voiceover timeline, burned-in captions, music, end card.

    edit.py <project> [--shots shots.json] [--out final/x.mp4] [--no-captions] [--preview]

Reads the shots file (see SKILL.md) and the word timings. Shots must touch end to end; each one fills
exactly start -> end, cut on the nearest frame, so cuts land on the words.
--preview renders fast at 540x960 to final/preview_<hook>.mp4. Otherwise the file is
final/<project>_<hook>_9x16_v<n>.mp4 with the next free version number.

Shot types: clip / talking (generated clips), avatar (an AI talking-avatar video, kept in sync),
image (a still with a slow push-in), text (a text card). Any shot can also carry "on_screen": "<text>".
Talking clips made with the video tool's own voice set "use_clip_audio": true; their sound is used.
It checks the plan first and stops with one line per problem (a missing file, an unknown type, a clip with
no sound track, a clip too short for its shot: "freeze_ok": true allows that one). Captions sit low on
avatar and talking shots and never on a text card or on-screen text: they move below (or above) it.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CLIP_TYPES, H, W, clip_path, duration, ffmpeg, find_font, run_ffmpeg

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--shots", default="shots.json")
ap.add_argument("--out")
ap.add_argument("--no-captions", action="store_true")
ap.add_argument("--preview", action="store_true")
a = ap.parse_args()

P = os.path.abspath(a.project)
if not ffmpeg():
    sys.exit("ffmpeg not found. Install it (see check_setup.py) and try again.")


def rel(path):
    """A path as the user sees it (inside the project); a full path when it's outside it or on another drive."""
    try:
        r = os.path.relpath(path, P)
    except ValueError:
        return path
    return os.path.abspath(path) if r.startswith("..") else r


def load_json(path, fix):
    """A JSON file (None if it doesn't exist); a broken one stops with its name and line, not a traceback."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:      # -sig: Notepad's byte-order mark is fine
            return json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        where = f" (line {e.lineno}: {e.msg})" if isinstance(e, json.JSONDecodeError) else ""
        sys.exit(f"{rel(path)} is not valid JSON{where}. {fix}")


def has_sound(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return " Audio: " in r.stderr


data = load_json(os.path.join(P, a.shots), "Fix that line (a missing comma, quote or bracket) and run again.")
if data is None:
    sys.exit(f"No shots file at {rel(os.path.join(P, a.shots))}. Write it first (\"The shots file\" in SKILL.md) "
             "or point --shots at it.")
if not isinstance(data, dict) or not isinstance(data.get("shots"), list) or not data["shots"]:
    sys.exit(f'{a.shots} has no shots: it needs a "shots" list with at least one shot ("The shots file" in SKILL.md; '
             "shots_draft.json is only the timing to build it from).")
shots = data["shots"]
if isinstance(data.get("music"), str):          # "music": "inputs/song.mp3" is a plain track
    data["music"] = {"file": data["music"]}
if isinstance(data.get("captions"), str):       # "captions": "clean" is a preset
    data["captions"] = {"preset": data["captions"]}

if not data.get("vo"):        # an AI avatar video is the voiceover as well as the picture (SKILL.md option 4)
    talker = next((s for s in shots if isinstance(s, dict) and s.get("type") == "avatar" and s.get("source")), None)
    if talker:
        data["vo"] = talker["source"]
        print(f"  no \"vo\" in {a.shots}: using the avatar video's sound ({talker['source']}) as the voiceover")
vo = os.path.join(P, data["vo"]) if data.get("vo") else None
m = re.match(r"shots_?(.*)\.json$", os.path.basename(a.shots))
hook = (m.group(1) if m and m.group(1) else "hookA")
user_cap = data.get("captions")
captions_on = not a.no_captions and user_cap is not False and (not isinstance(user_cap, dict) or user_cap.get("preset") != "none")

# A hook has its own voiceover, so its own word timings (SKILL.md Stage 4): never the main ad's words by mistake.
words_rel = data.get("words")
if not words_rel and m and m.group(1).startswith("hook"):
    own = f"words_{hook}.json"
    try:
        with open(os.path.join(P, "shots.json"), encoding="utf-8-sig") as f:
            main_vo = json.load(f).get("vo")
    except (OSError, ValueError, AttributeError):
        main_vo = None
    if os.path.exists(os.path.join(P, own)) or not vo or os.path.normpath(data["vo"]) != os.path.normpath(main_vo or ""):
        words_rel = own
        print(f'  no "words" in {a.shots}: using {own} (add "words": "{own}" to it, so every check reads that file)')
words_rel = words_rel or "words.json"
words_path = os.path.join(P, words_rel)

# ---------- 0. check the plan before any work: every problem at once, each naming its shot ----------
KINDS = CLIP_TYPES + ("image", "text", "avatar", "library", "footage")
problems, ids = [], set()


def need_file(what, path, sound=False):
    if not os.path.isfile(path):
        problems.append(f"{what} {rel(path)} doesn't exist")
    elif sound and not has_sound(path):
        problems.append(f"{what} {rel(path)} has no sound track")


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


if vo:
    need_file('the voiceover ("vo")', vo, sound=True)
for i, s in enumerate(shots):
    if not isinstance(s, dict):
        problems.append(f"shot {i + 1} isn't a {{...}} entry")
        continue
    sid = s.get("id")
    if not isinstance(sid, str) or not sid:
        problems.append(f'shot {i + 1} needs an "id" (a name like "s01")')
        continue
    if sid in ids:
        problems.append(f"{sid}: two shots have this id: give each its own")
    elif sid == "endcard":
        problems.append('a shot is called "endcard", the end card\'s own name: call it something else')
    ids.add(sid)
    if not (number(s.get("start")) and number(s.get("end"))):
        problems.append(f'{sid} needs a "start" and an "end" in seconds')
    for k, ok in (("in", lambda v: number(v) and v >= 0), ("speed", lambda v: number(v) and v > 0),
                  ("text_pos", lambda v: number(v) and 0 < v < 1),
                  ("caption_pos", lambda v: number(v) and 0 < v < 1 or v in ("middle", "low"))):
        if k in s and not ok(s[k]):
            problems.append(f'{sid}: "{k}" is {json.dumps(s[k])}, which isn\'t '
                            + ('"middle", "low" or a fraction of the height (0.5 = middle)' if k == "caption_pos" else
                               "a fraction of the height (0.5 = middle)" if k == "text_pos" else "a usable number"))
    kind = s.get("type", "clip")
    if kind not in KINDS:
        problems.append(f'{sid}: type "{kind}" isn\'t one of {", ".join(KINDS)}')
        continue
    if kind == "image":
        if s.get("source"):
            need_file(f"{sid}: image", os.path.join(P, s["source"]))
        else:
            problems.append(f'{sid}: an image shot needs "source" (the picture)')
    elif kind == "text":
        if s.get("source") or s.get("frame"):
            need_file(f"{sid}: background", os.path.join(P, s.get("source") or s.get("frame")))
    elif kind in CLIP_TYPES:      # a missing clip plays its frame as a still (below); a clip that's there must sound
        if s.get("use_clip_audio") and os.path.isfile(clip_path(P, s)) and not has_sound(clip_path(P, s)):
            problems.append(f'{sid}: "use_clip_audio" is set but {rel(clip_path(P, s))} has no sound track (Replicate '
                            'and Higgsfield make clips with the sound off). Remake it with sound, or lip-sync it '
                            'to a voiceover and take "use_clip_audio" off')
    elif not s.get("source") and not s.get("clip"):
        problems.append(f'{sid}: a {kind} shot needs "source" (the video file)')
    else:
        need_file(f"{sid}: video", clip_path(P, s), sound=bool(s.get("use_clip_audio")))
music = data.get("music")
if music:
    if not isinstance(music, dict) or not music.get("file"):
        problems.append('"music" needs "file" (the track), e.g. {"file": "inputs/music.mp3", "volume": 0.12}')
    else:
        need_file("the music", os.path.join(P, music["file"]), sound=True)
        if music.get("file2") and music.get("switch_at"):
            need_file("the second music track", os.path.join(P, music["file2"]), sound=True)
if data.get("endcard"):
    if not isinstance(data["endcard"], dict) or not data["endcard"].get("image"):
        problems.append('"endcard" needs "image", e.g. {"image": "frames/endcard.png", "seconds": 3}')
    else:
        need_file("the end card", os.path.join(P, data["endcard"]["image"]))
if isinstance(user_cap, dict) and user_cap.get("preset", "bold") not in ("bold", "clean", "none"):
    problems.append(f'captions preset "{user_cap["preset"]}" isn\'t one of bold, clean, none')
if problems:
    sys.exit(f"{a.shots}: fix {'this' if len(problems) == 1 else 'these'} and run again:\n  " + "\n  ".join(problems))
vo_len = duration(vo) if vo else 0.0


def timing_cmd():
    """The command that times this plan's voiceover into its words file."""
    is_hook = bool(m and m.group(1).startswith("hook"))
    script = f"inputs/script_{hook}.txt" if is_hook else "inputs/script.txt"
    if not os.path.exists(os.path.join(P, script)):
        script = "<this hook's script file>" if is_hook else "<the script file>"
    lang = f" --language {data['language']}" if data.get("language") else ""

    def q(x):       # a path with a space in it, quoted for the shell
        return f'"{x}"' if " " in x and not x.startswith("<") else x
    return f"python3 $S/transcribe.py {q(data['vo'])} . --script {q(script)} --words-out {q(words_rel)} --no-draft{lang}"


def load_words(path):
    """The word timings. An entry whose "w" was emptied by hand is dropped: there is nothing to show."""
    ws = load_json(path, "Run transcribe.py again (it was probably cut off), or fix that line." if vo else
                   f"Delete {rel(path)} and run edit.py again: it makes a new one from the clips' voices.")
    if not isinstance(ws, list):
        sys.exit(f"{rel(path)} isn't a list of words. Run transcribe.py again.")
    out = []
    for k, x in enumerate(ws):
        if not isinstance(x, dict) or not number(x.get("s")) or not number(x.get("e")):
            sys.exit(f'{rel(path)}: entry {k + 1} needs "w", "s" and "e" (the word, its start and end in seconds). '
                     "Fix it, or run transcribe.py again.")
        if str(x.get("w", "")).strip():
            out.append(dict(x, w=str(x["w"]).strip()))
    return out


notes = []                  # things to look at before showing the ad, repeated after "saved"
words = None
if vo and captions_on and not os.path.exists(words_path):
    # Without them the captions would be Whisper's guess at the mixed sound: brand names misspelled on screen.
    sys.exit(f"No word timings at {words_rel}. Time the voiceover first:\n  {timing_cmd()}"
             + (f'\nand add "words": "{words_rel}" to {a.shots}.' if not data.get("words") else "")
             + "\n(Or run edit.py with --no-captions.)")
if vo and os.path.exists(words_path):
    words = load_words(words_path)
    last = words[-1]["e"] if words else 0.0
    if not words:
        notes.append(f"{words_rel} has no words, so there are no captions. Time the voiceover again: {timing_cmd()}")
    elif last > vo_len + 0.5 or vo_len - last > 2.0:
        notes.append(f"WARNING {words_rel} ends at {last:.1f}s but the voiceover is {vo_len:.1f}s long: it was made "
                     f"from another take, so the captions would be out of sync. Time it again: {timing_cmd()}")
    elif os.path.getmtime(words_path) < os.path.getmtime(vo) - 1:
        notes.append(f"{data['vo']} changed after {words_rel} was made. If it's a new take, time it again "
                     f"({timing_cmd()}) or the captions drift.")
if a.out:
    out = os.path.join(P, a.out)
elif a.preview:
    out = os.path.join(P, "final", f"preview_{hook}.mp4")
else:
    base = os.path.join(P, "final", f"{os.path.basename(P)}_{hook}_9x16_v")
    n = 1
    while os.path.exists(f"{base}{n}.mp4"):
        n += 1
    out = f"{base}{n}.mp4"
tmp = os.path.join(P, "tmp", hook)
os.makedirs(tmp, exist_ok=True)
os.makedirs(os.path.dirname(out), exist_ok=True)
w, h = (540, 960) if a.preview else (W, H)
FPS = 30
enc = ["-c:v", "libx264", "-preset", "ultrafast" if a.preview else "medium", "-crf", "18",
       "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
fill = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS}"

# Shots are joined in list order, so each must start where the one before ends (the first at 0),
# or every later cut moves off its words.
t = 0.0
for s in shots:
    if abs(s["start"] - t) > 0.001 or s["end"] <= s["start"]:
        sys.exit(f"{s['id']} runs {s['start']}-{s['end']}s but should start at {t}s and end after that: shots must "
                 "touch end to end, in time order (each start = the previous end). Fix the shots file and run again.")
    t = s["end"]

# The last shot runs to the end of the voiceover; an end card (optional) goes after it.
plan_end = shots[-1]["end"]
shots[-1]["end"] = max(plan_end, vo_len)
late = [x for x in words if x["s"] >= plan_end - 0.05] if words else []     # whole words after the plan
if vo and vo_len - plan_end > 1.0 and (late or words is None):
    notes.append(f"{shots[-1]['id']} runs on to the end of the voiceover: the plan ends at {plan_end:.1f}s but the "
                 f"voiceover is {vo_len:.1f}s long ({vo_len - plan_end:.1f}s under one picture"
                 + (f', from "{late[0]["w"]}" on' if late else "")
                 + "). Add shots for the last lines, or set its end yourself.")
segments = list(shots)
if data.get("endcard"):
    ec = data["endcard"]
    segments.append({"id": "endcard", "type": "image", "source": ec["image"],
                     "start": shots[-1]["end"], "end": shots[-1]["end"] + ec.get("seconds", 3), "zoom": False})
total = segments[-1]["end"]


# ---------- 1. picture, one segment per shot ----------
def still(sid, src, n, seg, zoom=True):
    if zoom:    # slow push-in so stills don't look frozen
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='min(zoom+0.0007,1.08)':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":s={w}x{h}:fps={FPS},setsar=1")
    else:
        vf = fill
    cut(sid, ["-loop", "1", "-i", src, "-vf", vf, "-frames:v", str(n)] + enc + [seg])


def check_in(s, src, start_in, d):
    # Starting at or past the clip's end makes an empty segment, and every later shot would move up.
    sid = s["id"]
    n = duration(src)
    if start_in >= n - 1.0 / FPS:
        sys.exit(f'{sid} would start {start_in}s into {rel(src)}, which is only {n:.2f}s long. '
                 'Check its "in" (or the clip).')
    # Too little clip after "in": the segment holds its last frame still for the rest of the shot.
    left = (n - start_in) / s.get("speed", 1.0)
    frozen = d - left
    if frozen <= 0.25 or s.get("freeze_ok"):
        return
    if sid == shots[-1]["id"] and words and s["start"] + left >= words[-1]["e"]:
        notes.append(f"{sid} holds its last frame for its last {frozen:.1f}s, after the last word (the voiceover's "
                     "quiet end). Fine for a closing shot; look at it.")
        return
    remake = (f"remake it (generate.py clips . --only {sid} --redo)" if s.get("type", "clip") in CLIP_TYPES
              else "use a longer clip")
    stretched = sid == shots[-1]["id"] and shots[-1]["end"] > plan_end + 0.01
    sys.exit((f"{sid} runs on to the end of the voiceover (the plan ends at {plan_end:.1f}s), so it" if stretched
              else sid) + f' plays {d:.2f}s from {start_in}s into {rel(src)}, which is only {n:.2f}s long: the last '
             f'{frozen:.2f}s would be a frozen frame. '
             + ("Add shots for the last lines, set" if stretched else "Set") + f' a smaller "in", '
             + ("" if stretched else "shorten the shot, ") + f'or {remake}. ("freeze_ok": true on the shot allows it.)')


def cut(sid, args):
    try:
        run_ffmpeg(args)
    except SystemExit as e:       # name the shot, not just ffmpeg's error
        sys.exit(f"{sid}: couldn't cut this shot. {e.code}")


parts = []
clip_audio = []          # (path, in-point, start on timeline, length) for shots that keep their own sound
pos = 0                  # frames so far: each segment ends on the frame nearest its end time, so cuts don't drift
for s in segments:
    d = round(s["end"] - s["start"], 3)
    n = round(s["end"] * FPS) - pos
    pos += n
    if n < 1:
        sys.exit(f"{s['id']} is {d}s long, shorter than one frame. Make it longer or remove it.")
    seg = os.path.join(tmp, s["id"] + ".mp4")
    kind = s.get("type", "clip")
    src = clip_path(P, s)
    if kind in CLIP_TYPES and not os.path.exists(src):
        if s.get("frame") and os.path.exists(os.path.join(P, s["frame"])):
            print(f"  {s['id']}: no clip yet, using its start frame as a still")
            if s.get("use_clip_audio"):
                notes.append(f"{s['id']} has no clip yet, so its line is silent (its voice comes from the clip). "
                             f"Make it (generate.py clips . --only {s['id']}) before this goes to anyone.")
            kind, s = "image", dict(s, source=s["frame"])
        else:
            sys.exit(f"{s['id']} has no clip: {rel(src)} doesn't exist. Make it (generate.py clips . --only {s['id']}), "
                     'point "clip" at the right file, or give the shot a "frame" to show as a still for now.')
    if kind == "image":
        still(s["id"], os.path.join(P, s["source"]), n, seg, s.get("zoom", True))
    elif kind == "text":
        bg = s.get("source") or s.get("frame")
        if bg and os.path.splitext(bg)[1].lower() in (".mp4", ".mov"):
            check_in(s, os.path.join(P, bg), s.get("in", 0), d)
            cut(s["id"], ["-ss", f"{s.get('in', 0)}", "-i", os.path.join(P, bg), "-vf",
                          f"{fill},tpad=stop_mode=clone:stop_duration={d}", "-frames:v", str(n)] + enc + [seg])
        elif bg:
            still(s["id"], os.path.join(P, bg), n, seg, s.get("zoom", True))
        else:
            cut(s["id"], ["-f", "lavfi", "-i", f"color=c={s.get('bg', '#111111')}:s={w}x{h}:r={FPS}",
                          "-frames:v", str(n)] + enc + [seg])
    else:
        start_in = s.get("in", s["start"] if kind in ("avatar", "footage") else 0)   # library clips start at 0 unless "in" is set
        check_in(s, src, start_in, d)
        speed = s.get("speed", 1.0)       # only ever set when the user asks
        vf = f"setpts=PTS/{speed},{fill},tpad=stop_mode=clone:stop_duration={d}"
        cut(s["id"], ["-ss", f"{start_in}", "-i", src, "-vf", vf, "-frames:v", str(n)] + enc + [seg])
        if s.get("use_clip_audio"):
            clip_audio.append((src, start_in, s["start"], d))
    parts.append(seg)

listfile = os.path.join(tmp, "concat.txt")
# Bare names (the segments sit next to the list): a quote in a full path breaks it.
with open(listfile, "w", encoding="utf-8") as f:
    f.writelines("file '%s'\n" % os.path.basename(p).replace("'", "'\\''") for p in parts)
video = os.path.join(tmp, "video.mp4")
run_ffmpeg(["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", video])
if abs(duration(video) - total) > 1.0 / FPS:
    sys.exit(f"The picture came out {duration(video):.2f}s long but the shots add up to {total:.2f}s: a shot is "
             'empty or too short. Check the clips and their "in" points.')

# ---------- 2. sound: voiceover + clip voices + music, loudness-normalised, to a WAV ----------
# Picture and sound are made separately and joined at the end. Doing both in one filter graph
# dropped 3-second chunks of the voiceover in testing, so keep these steps apart.
snd = os.path.join(tmp, "sound.wav")
ins, labels, chains = [], [], []
n_in = 0                  # ffmpeg input index
if vo:
    ins += ["-i", vo]
    n_in += 1
    chains.append(f"[0:a]apad=whole_dur={total}[vo]")
    labels.append("[vo]")
for src, start_in, at, d in clip_audio:
    k = n_in
    n_in += 1
    ins += ["-ss", f"{start_in}", "-t", f"{d}", "-i", src]
    ms = int(at * 1000)
    chains.append(f"[{k}:a]atrim=0:{d},adelay={ms}|{ms},apad=whole_dur={total}[c{k}]")
    labels.append(f"[c{k}]")
music = data.get("music")
voices = list(labels)                 # the voiceover and any clip voices
mus_label = None
if music:
    # One track, or two: "file2" takes over at "switch_at" seconds.
    vol = music.get("volume", 0.12)
    k = n_in
    n_in += 1
    ins += ["-stream_loop", "-1", "-i", os.path.join(P, music["file"])]
    sw = music.get("switch_at") if music.get("file2") else None
    if sw:
        k2 = n_in
        n_in += 1
        ins += ["-stream_loop", "-1", "-i", os.path.join(P, music["file2"])]
        ms = int(sw * 1000)
        chains.append(f"[{k}:a]volume={vol},atrim=0:{sw + 0.4},afade=t=out:st={max(sw - 0.1, 0)}:d=0.5,"
                      f"apad=whole_dur={total}[m1]")
        chains.append(f"[{k2}:a]volume={music.get('volume2', vol)},atrim=0:{max(total - sw, 0.1)},afade=t=in:d=0.4,"
                      f"adelay={ms}|{ms},apad=whole_dur={total}[m2]")
        chains.append(f"[m1][m2]amix=inputs=2:normalize=0,atrim=0:{total},"
                      f"afade=t=out:st={max(total - 1.5, 0)}:d=1.5[mu]")
    else:
        chains.append(f"[{k}:a]volume={vol},atrim=0:{total},"
                      f"afade=t=out:st={max(total - 1.5, 0)}:d=1.5[mu]")
    mus_label = "[mu]"
if voices and mus_label and music.get("duck", True):
    # Duck the music under the voice: it dips while someone speaks and comes back up in the gaps.
    vin = "".join(voices)
    chains.append(f"{vin}amix=inputs={len(voices)}:normalize=0[vx]" if len(voices) > 1 else f"{vin}anull[vx]")
    chains.append("[vx]asplit=2[vmain][vkey]")
    chains.append("[mu][vkey]sidechaincompress=threshold=0.015:ratio=8:attack=15:release=350[mud]")
    labels = ["[vmain]", "[mud]"]
elif mus_label:
    labels = voices + [mus_label]
if not labels:
    ins += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
    chains.append("[0:a]atrim=0:%s[si]" % total)
    labels.append("[si]")
mix = (f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0," if len(labels) > 1 else f"{labels[0]}anull,")
# asetpts: loudnorm shifts the timestamps, and without it -t cut the last 25-75ms of the sound
af = ";".join(chains) + f";{mix}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asetpts=N/SR/TB[a]"
try:
    run_ffmpeg(ins + ["-filter_complex", af, "-map", "[a]", "-t", f"{total}", "-c:a", "pcm_s16le", snd])
except SystemExit as e:
    sys.exit(f"The sound mix (voiceover, clip voices, music) failed. {e.code}")


# ---------- 3. captions and text cards (ASS, burned in) ----------
def ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def ass_colour(hexstr):
    hexstr = hexstr.lstrip("#")
    return f"&H00{hexstr[4:6]}{hexstr[2:4]}{hexstr[0:2]}&"


def ass_text(t):
    """Text as libass shows it: { } open a code block (the text inside vanishes) and a backslash starts a code."""
    return t.replace("\\", "/").replace("{", "(").replace("}", ")")


def card_text(s):
    """A shot's text card or on-screen text, ready for libass; None if it has none."""
    txt = s.get("on_screen") or (s.get("text") if s.get("type") == "text" else None)
    return ass_text(str(txt)) if txt else None


PRESETS = {
    "bold":  {"uppercase": True, "lines": 1, "max_words": 3, "size": 104, "highlight": "#FFE600"},
    "clean": {"uppercase": False, "lines": 2, "max_words": 6, "size": 92, "highlight": None},
}
cap = {"preset": "bold", "font": None, "font_file": None, "max_width": 0.86, "outline": 9,
       "colour": "#FFFFFF", "position": "middle"}
if isinstance(user_cap, dict):
    cap.update(PRESETS.get(user_cap.get("preset", "bold"), PRESETS["bold"]))
    cap.update(user_cap)
else:
    cap.update(PRESETS["bold"])
cap["font"], cap["font_file"] = find_font(cap["font"], cap["font_file"])
scale = h / H
fsize = int(cap["size"] * scale)
outline = max(1, int(cap["outline"] * scale))
card_size = int(data.get("card_size", 104) * scale)
events = []

has_speech = bool(vo) or bool(clip_audio)
# With no voiceover the words are heard from the clips' own voices. Note which clips (and where) they were
# heard from, so a remade, moved or trimmed talking clip gets new captions instead of the old words.
heard_from = words_path + ".src"
stale = False
if not vo:
    def recorded(src):      # as the record has always named a clip (relative), so earlier records still match
        try:
            return os.path.relpath(src, P)
        except ValueError:
            return src
    heard = json.dumps([[recorded(src), os.path.getmtime(src), start_in, at, d] for src, start_in, at, d in clip_audio])
    if os.path.exists(words_path) and not os.path.exists(heard_from):
        with open(heard_from, "w", encoding="utf-8") as f:    # words made before this record existed: keep them
            f.write(heard)
    elif os.path.exists(words_path):
        with open(heard_from, encoding="utf-8") as f:
            stale = f.read() != heard
if not vo and clip_audio and (stale or not os.path.exists(words_path)):
    # No word timings yet, or the clips' voices changed: transcribe the finished sound. Captions or not:
    # verify_vo.py and qc.py check the ad against these words too.
    if stale:
        print(f"  the clips' voices changed since {words_rel} was made: transcribing them again")
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe.py"),
                        snd, P, "--no-draft", "--words-out", words_rel]
                       + (["--language", data["language"]] if data.get("language") else []))
    if r.returncode != 0:
        sys.exit("Couldn't hear the words in the clips' voices: transcribe.py stopped (its message is above). "
                 "Fix that and run edit.py again.")
    with open(heard_from, "w", encoding="utf-8") as f:
        f.write(heard)
    if captions_on:
        notes.append(f"The captions are the clips' voices as Whisper heard them, with no script to check them "
                     f"against: read them in the preview, and fix a misheard word in {words_rel} (its \"w\").")
if words is None and has_speech and os.path.exists(words_path):
    words = load_words(words_path)

if captions_on and has_speech and words:
    from PIL import ImageFont
    try:
        measure = ImageFont.truetype(cap["font_file"], fsize)
        if cap["lines"] > 1:    # lines are broken here, so measure at the size libass draws (ascent + descent = fsize)
            measure = ImageFont.truetype(cap["font_file"], round(fsize * fsize / sum(measure.getmetrics())))
        card_font = ImageFont.truetype(cap["font_file"], card_size)
        card_font = ImageFont.truetype(cap["font_file"], round(card_size * card_size / sum(card_font.getmetrics())))
    except (OSError, TypeError):
        measure = card_font = ImageFont.load_default()
    limit = int(w * cap["max_width"])     # one line
    PUNCT = set(".?!,;:…")

    def show(x):
        return ass_text(x["w"].upper() if cap["uppercase"] else x["w"])

    def width(ch):
        return measure.getlength(" ".join(show(x) for x in ch)) + 2 * outline

    def rows(ch):
        # Break the lines here with the same measure, so libass never wraps (and never makes a 3rd line).
        out = [[]]
        for x in ch:
            if out[-1] and width(out[-1] + [x]) > limit:
                out.append([])
            out[-1].append(x)
        return out

    def join(lines, texts):
        out, k = [], 0
        for r in lines:
            out.append(" ".join(texts[k:k + len(r)]))
            k += len(r)
        return "\\N".join(out)

    def mark(x):      # the word's closing mark, past quotes and brackets ("encore ?»" ends a sentence)
        return x["w"].rstrip("\"'»”’)]")[-1:]

    def weak(x):      # "a", "the", "and", "I'm": a caption or a line shouldn't end on one
        letters = re.sub(r"\W", "", x["w"])
        return mark(x) not in PUNCT and letters.isalpha() and len(letters) <= 3

    def fits(ch):
        return len(ch) <= cap["max_words"] and len(rows(ch)) <= cap["lines"]

    def split(cl):
        """A clause in the fewest captions that fit, as even as possible. A caption ends on a short word, or
        holds a lone word, only when nothing else fits."""
        best = {0: (0, 0.0, 0)}      # words placed -> (captions, cost, where the last caption starts)
        for j in range(1, len(cl) + 1):
            for i in range(j - 1, -1, -1):
                piece = cl[i:j]
                if len(piece) > 1 and not fits(piece):
                    break            # a longer one won't fit either (a lone long word shrinks to fit)
                cost = (width(piece) / limit) ** 2
                if j < len(cl) and weak(piece[-1]):
                    cost += 0.5
                if len(piece) == 1 and len(cl) > 1:
                    cost += 1
                cand = (best[i][0] + 1, best[i][1] + cost, i)
                if j not in best or cand[:2] < best[j][:2]:
                    best[j] = cand
        out, j = [], len(cl)
        while j:
            out.append(cl[best[j][2]:j])
            j = best[j][2]
        return out[::-1]

    def layout(ch):
        """The caption's lines: one when it fits, else two, broken where they come out most even."""
        lines = rows(ch)
        if len(lines) != 2:
            return lines
        ok = [k for k in range(1, len(ch)) if width(ch[:k]) <= limit and width(ch[k:]) <= limit]
        if not ok:
            return lines
        k = min(ok, key=lambda k: max(width(ch[:k]), width(ch[k:])) + (limit / 4 if weak(ch[k - 1]) else 0))
        return [ch[:k], ch[k:]]

    # A caption ends at punctuation or a pause; a longer stretch is shared out evenly over as few as fit.
    clauses, cur = [], []
    for i, wd in enumerate(words):
        cur.append(wd)
        gap = words[i + 1]["s"] - wd["e"] if i + 1 < len(words) else 9
        if mark(wd) in PUNCT or gap > 0.35:
            clauses.append(cur)
            cur = []
    if cur:
        clauses.append(cur)
    chunks = [piece for cl in clauses for piece in split(cl)]

    # Captions sit in the middle, or low (a little below it) on avatar and talking shots, whose face is in the
    # middle. A shot's "caption_pos" ("middle", "low" or a fraction of the height) sets it. Never the top, and
    # never on a text card or on-screen text: they go just below it, or above it when there's no room below.
    ypos = {"middle": 0.5, "low": 0.667}
    space = int(0.02 * h)
    said = set()

    def card_box(s):
        """Top and bottom (pixels) of a shot's text card or on-screen text, wrapped as libass wraps it."""
        txt = card_text(s)
        if not txt:
            return None
        room, n = w - 2 * int(90 * scale), 0
        for para in txt.split("\n"):
            line = ""
            n += 1
            for word in para.split():
                if line and card_font.getlength(f"{line} {word}") > room:
                    n += 1
                    line = word
                else:
                    line = f"{line} {word}".strip()
        y = h * s.get("text_pos", 0.5)
        return y - n * card_size / 2 - outline, y + n * card_size / 2 + outline

    def place(ch, lines, t1):
        """Where the caption's centre goes (pixels down), or None when a card leaves it no room."""
        t0 = ch[0]["s"]
        over = [s for s in shots if s["start"] < t1 and s["end"] > t0]      # shots it is on screen over
        first = next((s for s in over if s["start"] <= t0 < s["end"]), over[0] if over else {})
        talking = first.get("type") in ("avatar", "talking") or first.get("use_clip_audio")
        p = first.get("caption_pos", "low" if talking else cap.get("position", "middle"))
        want = h * min(max(p if number(p) else ypos.get(p, 0.5), 0.35), 0.8)
        half = len(lines) * fsize / 2 + outline
        boxes = [(s, b) for s in over for b in [card_box(s)] if b]

        def clear(y, bs):
            return all(y + half + space <= top or y - half - space >= bot for _, (top, bot) in bs)

        spots = [y for y in [want] + [y for _, (top, bot) in boxes for y in (bot + space + half, top - space - half)]
                 if h * 0.35 <= y <= h * 0.8 and clear(y, boxes)]
        y = min(spots, key=lambda y: (abs(y - want), y < want)) if spots else None    # nearest; below on a tie
        for s, b in boxes:
            what = "text card" if s.get("type") == "text" and not s.get("on_screen") else "on-screen text"
            if clear(want, [(s, b)]) or (s["id"], y is None) in said:
                continue
            said.add((s["id"], y is None))
            if y is None:
                notes.append(f'{s["id"]}: no captions over its {what}: it fills the middle of the frame. Fine if it '
                             'says the line; otherwise make it shorter or move it with "text_pos".')
            else:
                print(f'  {s["id"]}: captions moved {"below" if y > want else "above"} its {what} so they don\'t '
                      f'cover it ("text_pos" moves the {what})')
        return None if y is None else int(y)

    last_end = shots[-1]["end"]           # the end card is a picture of its own: no caption runs onto it
    for ci, ch in enumerate(chunks):
        end = min(chunks[ci + 1][0]["s"], ch[-1]["e"] + 0.6) if ci + 1 < len(chunks) else ch[-1]["e"] + 0.6
        end = min(end, last_end)
        texts = [show(x) for x in ch]
        if end <= ch[0]["s"]:
            continue
        lines = layout(ch)
        y = place(ch, lines, end)
        if y is None:
            continue
        widest = max(width(r) for r in lines)
        fit = "" if widest <= limit else "{\\fs%d}" % int(fsize * limit / widest)   # a long word shrinks, never wraps
        tag = "{\\an5\\pos(%d,%d)}" % (w // 2, y) + fit + "{\\q2}"
        if cap.get("highlight"):
            for wi, wd in enumerate(ch):
                st = ch[0]["s"] if wi == 0 else wd["s"]
                en = ch[wi + 1]["s"] if wi + 1 < len(ch) else end
                if en <= st:
                    continue
                body = join(lines, [("{\\c" + ass_colour(cap["highlight"]) + "}" + t + "{\\c" + ass_colour(cap["colour"]) + "}")
                                    if k == wi else t for k, t in enumerate(texts)])
                events.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Cap,,0,0,0,,{tag}{body}")
        else:
            events.append(f"Dialogue: 0,{ass_time(ch[0]['s'])},{ass_time(end)},Cap,,0,0,0,,{tag}{join(lines, texts)}")

# Text cards and on-screen text: centred, wrap onto as many lines as needed, inside the 4:5 zone.
for s in shots:
    txt = card_text(s)
    if txt:
        if txt != str(s.get("on_screen") or s.get("text")):
            print(f"  {s['id']}: {{ }} and \\ in its text show as ( ) and / (libass reads them as codes)")
        body = txt.replace("\n", "\\N")
        events.append(f"Dialogue: 1,{ass_time(s['start'])},{ass_time(s['end'])},Card,,0,0,0,,"
                      "{\\an5\\pos(%d,%d)\\q0}%s" % (w // 2, int(h * s.get("text_pos", 0.5)), body))

# Final picture encode: high quality but capped, so a 60s ad is ~50MB, not ~100MB+.
# "max_mbps" in the shots file changes the cap (8 suits Meta, TikTok and YouTube Shorts at 1080x1920).
mbps = data.get("max_mbps", 8)
final_enc = ["-c:v", "libx264", "-preset", "ultrafast" if a.preview else "medium", "-crf", "21",
             "-maxrate", f"{mbps}M", "-bufsize", f"{mbps * 2}M", "-pix_fmt", "yuv420p", "-an"]
pic = os.path.join(tmp, "picture.mp4")
if not events:
    run_ffmpeg(["-i", video] + final_enc + [pic])
if events:
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{cap['font']},{fsize},{ass_colour(cap['colour'])},&H000000FF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,{outline},0,5,{int(60 * scale)},{int(60 * scale)},0,1
Style: Card,{cap['font']},{card_size},&H00FFFFFF&,&H000000FF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,{outline},0,5,{int(90 * scale)},{int(90 * scale)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(os.path.join(tmp, "captions.ass"), "w", encoding="utf-8") as f:     # libass reads UTF-8
        f.write(ass + "\n".join(events) + "\n")
    vf = "ass=captions.ass"
    if cap["font_file"]:
        # libass gets a copy of the font next to the captions: a drive colon (C:/Windows/Fonts) or a quote
        # in the font's own folder breaks the filter.
        fonts = os.path.join(tmp, "fonts")
        shutil.rmtree(fonts, ignore_errors=True)
        os.makedirs(fonts)
        shutil.copy(cap["font_file"], fonts)
        vf += ":fontsdir=fonts"
    r = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-vf", vf]
                       + final_enc + [pic], cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit("ffmpeg failed (captions):\n" + r.stderr[-2000:])

# ---------- 4. join picture and sound (picture copied, sound encoded once) ----------
run_ffmpeg(["-i", pic, "-i", snd, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total}", "-movflags", "+faststart", out])

# ---------- 5. quick sound check: full length, no early end ----------
r = subprocess.run([ffmpeg(), "-hide_banner", "-i", out, "-map", "0:a", "-f", "null", "-"], capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
times = re.findall(r"time=(\d+):(\d+):([\d.]+)", r.stderr)
audio_len = (lambda t: int(t[0]) * 3600 + int(t[1]) * 60 + float(t[2]))(times[-1]) if times else 0
print(f"saved {out}  ({total:.1f}s, {len(segments)} shots"
      f"{', captions' if any(e.startswith('Dialogue: 0') for e in events) else ''}"
      f"{', text cards' if any(e.startswith('Dialogue: 1') for e in events) else ''}{', music' if music else ''})")
if notes:
    print(f"Look at {'this' if len(notes) == 1 else 'these'} before showing it:")
    for x in notes:
        print("  -", x)
if abs(audio_len - total) > 0.3:
    sys.exit(f"SOUND CHECK FAILED: the sound is {audio_len:.2f}s long, the ad is {total:.2f}s")
if has_speech:
    print("Sound is full length. Now run verify_vo.py on this file for the word-by-word check.")
