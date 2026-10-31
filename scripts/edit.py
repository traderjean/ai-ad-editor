"""Cut the ad: shots on the voiceover timeline, burned-in captions, music, end card.

    edit.py <project> [--shots shots.json] [--out final/x.mp4] [--no-captions] [--preview]

Reads the shots file (see SKILL.md) and the word timings. Shots must touch end to end; each one fills
exactly start -> end, cut on the nearest frame, so cuts land on the words.
--preview renders fast at 540x960 to final/preview_<hook>.mp4. Otherwise the file is
final/<project>_<hook>_9x16_v<n>.mp4 with the next free version number.

Shot types: clip / talking (generated clips), avatar (an AI talking-avatar video, kept in sync),
image (a still with a slow push-in), text (a text card). Any shot can also carry "on_screen": "<text>".
Talking clips made with the video tool's own voice set "use_clip_audio": true; their sound is used.
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
with open(os.path.join(P, a.shots), encoding="utf-8") as f:
    data = json.load(f)
shots = data["shots"]


def rel(path):
    """A path as the user sees it (inside the project); a full path when it's on another drive."""
    try:
        return os.path.relpath(path, P)
    except ValueError:
        return path


if not data.get("vo"):        # an AI avatar video is the voiceover as well as the picture (SKILL.md option 4)
    talker = next((s for s in shots if s.get("type") == "avatar" and s.get("source")), None)
    if talker:
        data["vo"] = talker["source"]
        print(f"  no \"vo\" in {a.shots}: using the avatar video's sound ({talker['source']}) as the voiceover")
vo = os.path.join(P, data["vo"]) if data.get("vo") else None
vo_len = duration(vo) if vo else 0.0
m = re.match(r"shots_?(.*)\.json$", os.path.basename(a.shots))
hook = (m.group(1) if m and m.group(1) else "hookA")
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
shots[-1]["end"] = max(shots[-1]["end"], vo_len)
segments = list(shots)
if data.get("endcard"):
    ec = data["endcard"]
    segments.append({"id": "endcard", "type": "image", "source": ec["image"],
                     "start": shots[-1]["end"], "end": shots[-1]["end"] + ec.get("seconds", 3), "zoom": False})
total = segments[-1]["end"]


# ---------- 1. picture, one segment per shot ----------
def still(src, n, seg, zoom=True):
    if zoom:    # slow push-in so stills don't look frozen
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='min(zoom+0.0007,1.08)':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":s={w}x{h}:fps={FPS},setsar=1")
    else:
        vf = fill
    run_ffmpeg(["-loop", "1", "-i", src, "-vf", vf, "-frames:v", str(n)] + enc + [seg])


def check_in(sid, src, start_in):
    # Starting at or past the clip's end makes an empty segment, and every later shot would move up.
    n = duration(src)
    if start_in >= n - 1.0 / FPS:
        sys.exit(f'{sid} would start {start_in}s into {rel(src)}, which is only {n:.2f}s long. '
                 'Check its "in" (or the clip).')


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
            kind, s = "image", dict(s, source=s["frame"])
        else:
            sys.exit(f"Missing clip for {s['id']}: {src}")
    if kind == "image":
        still(os.path.join(P, s["source"]), n, seg, s.get("zoom", True))
    elif kind == "text":
        bg = s.get("source") or s.get("frame")
        if bg and os.path.splitext(bg)[1].lower() in (".mp4", ".mov"):
            check_in(s["id"], os.path.join(P, bg), s.get("in", 0))
            run_ffmpeg(["-ss", f"{s.get('in', 0)}", "-i", os.path.join(P, bg), "-vf",
                        f"{fill},tpad=stop_mode=clone:stop_duration={d}", "-frames:v", str(n)] + enc + [seg])
        elif bg:
            still(os.path.join(P, bg), n, seg, s.get("zoom", True))
        else:
            run_ffmpeg(["-f", "lavfi", "-i", f"color=c={s.get('bg', '#111111')}:s={w}x{h}:r={FPS}",
                        "-frames:v", str(n)] + enc + [seg])
    else:
        start_in = s.get("in", s["start"] if kind in ("avatar", "footage") else 0)   # library clips start at 0 unless "in" is set
        check_in(s["id"], src, start_in)
        speed = s.get("speed", 1.0)       # only ever set when the user asks
        vf = f"setpts=PTS/{speed},{fill},tpad=stop_mode=clone:stop_duration={d}"
        run_ffmpeg(["-ss", f"{start_in}", "-i", src, "-vf", vf, "-frames:v", str(n)] + enc + [seg])
        if s.get("use_clip_audio"):
            clip_audio.append((src, start_in, s["start"], d))
    parts.append(seg)

listfile = os.path.join(tmp, "concat.txt")
with open(listfile, "w") as f:    # bare names (the segments sit next to the list): a quote in a full path breaks it
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
run_ffmpeg(ins + ["-filter_complex", af, "-map", "[a]", "-t", f"{total}", "-c:a", "pcm_s16le", snd])


# ---------- 3. captions and text cards (ASS, burned in) ----------
def ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def ass_colour(hexstr):
    hexstr = hexstr.lstrip("#")
    return f"&H00{hexstr[4:6]}{hexstr[2:4]}{hexstr[0:2]}&"


PRESETS = {
    "bold":  {"uppercase": True, "lines": 1, "max_words": 3, "size": 104, "highlight": "#FFE600"},
    "clean": {"uppercase": False, "lines": 2, "max_words": 6, "size": 92, "highlight": None},
}
user_cap = data.get("captions")
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
events = []

words_path = os.path.join(P, data.get("words", "words.json"))
captions_on = not a.no_captions and user_cap is not False and (not isinstance(user_cap, dict) or user_cap.get("preset") != "none")
has_speech = bool(vo) or bool(clip_audio)
# With no voiceover the words are heard from the clips' own voices. Note which clips (and where) they were
# heard from, so a remade, moved or trimmed talking clip gets new captions instead of the old words.
heard_from = words_path + ".src"
stale = False
if not vo:
    heard = json.dumps([[rel(src), os.path.getmtime(src), start_in, at, d] for src, start_in, at, d in clip_audio])
    if os.path.exists(words_path) and not os.path.exists(heard_from):
        with open(heard_from, "w", encoding="utf-8") as f:    # words made before this record existed: keep them
            f.write(heard)
    elif os.path.exists(words_path):
        with open(heard_from, encoding="utf-8") as f:
            stale = f.read() != heard
if captions_on and has_speech and (stale or not os.path.exists(words_path)):
    # No word timings yet, or the clips' voices changed: transcribe the finished sound.
    if stale:
        print(f"  the clips' voices changed since {rel(words_path)} was made: transcribing them again")
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe.py"),
                    snd, P, "--no-draft", "--words-out", rel(words_path)]
                   + (["--language", data["language"]] if data.get("language") else []), check=True)
    if not vo:
        with open(heard_from, "w", encoding="utf-8") as f:
            f.write(heard)

if captions_on and has_speech and os.path.exists(words_path):
    from PIL import ImageFont
    with open(words_path, encoding="utf-8") as f:
        words = json.load(f)
    try:
        measure = ImageFont.truetype(cap["font_file"], fsize)
        if cap["lines"] > 1:    # lines are broken here, so measure at the size libass draws (ascent + descent = fsize)
            measure = ImageFont.truetype(cap["font_file"], round(fsize * fsize / sum(measure.getmetrics())))
    except (OSError, TypeError):
        measure = ImageFont.load_default()
    limit = int(w * cap["max_width"])     # one line

    def show(x):
        return x["w"].upper() if cap["uppercase"] else x["w"]

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

    # A chunk ends at punctuation, a pause, max_words, or when the next word would need one line too many.
    chunks, cur = [], []
    for i, wd in enumerate(words):
        if cur and len(rows(cur + [wd])) > cap["lines"]:
            chunks.append(cur)
            cur = []
        cur.append(wd)
        gap = words[i + 1]["s"] - wd["e"] if i + 1 < len(words) else 9
        if len(cur) >= cap["max_words"] or wd["w"][-1] in ".?!,;:" or gap > 0.35:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    # Captions sit in the middle. A shot whose main face or object is in the middle sets
    # "caption_pos": "low" (a little below the middle) or a fraction of the height. Never the top.
    ypos = {"middle": 0.5, "low": 0.667}

    def pos_tag(t):
        p = cap.get("position", "middle")
        for s in shots:
            if s["start"] <= t < s["end"]:
                p = s.get("caption_pos", p)
                break
        frac = p if isinstance(p, (int, float)) else ypos.get(p, 0.5)
        return "{\\an5\\pos(%d,%d)}" % (w // 2, int(h * min(max(frac, 0.35), 0.8)))

    for ci, ch in enumerate(chunks):
        end = min(chunks[ci + 1][0]["s"], ch[-1]["e"] + 0.6) if ci + 1 < len(chunks) else ch[-1]["e"] + 0.6
        texts = [show(x) for x in ch]
        lines = rows(ch)
        widest = max(width(r) for r in lines)
        fit = "" if widest <= limit else "{\\fs%d}" % int(fsize * limit / widest)   # a long word shrinks, never wraps
        tag = pos_tag(ch[0]["s"]) + fit + "{\\q2}"
        if cap.get("highlight"):
            for wi, wd in enumerate(ch):
                st = ch[0]["s"] if wi == 0 else wd["s"]
                en = ch[wi + 1]["s"] if wi + 1 < len(ch) else end
                body = join(lines, [("{\\c" + ass_colour(cap["highlight"]) + "}" + t + "{\\c" + ass_colour(cap["colour"]) + "}")
                                    if k == wi else t for k, t in enumerate(texts)])
                events.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Cap,,0,0,0,,{tag}{body}")
        else:
            events.append(f"Dialogue: 0,{ass_time(ch[0]['s'])},{ass_time(end)},Cap,,0,0,0,,{tag}{join(lines, texts)}")

# Text cards and on-screen text: centred, wrap onto as many lines as needed, inside the 4:5 zone.
for s in shots:
    txt = s.get("on_screen") or (s.get("text") if s.get("type") == "text" else None)
    if txt:
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
    card_size = int(data.get("card_size", 104) * scale)
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
if abs(audio_len - total) > 0.3:
    sys.exit(f"SOUND CHECK FAILED: the sound is {audio_len:.2f}s long, the ad is {total:.2f}s")
if vo:
    print("Sound is full length. Now run verify_vo.py on this file for the word-by-word check.")
