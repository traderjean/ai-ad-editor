"""A hook variant: a new opening line in front of the main ad, the rest of the ad reused as it is.

    hook.py <project> <letter> --line-audio audio/hookB_line.mp3 [--line "<the hook line>"] [--from s02]
            [--language fr] [--trust-script] [--force]
    hook.py <project> <letter> [--from s02]       same opening line, new visuals (no new audio)

The main voiceover is never changed. The hook line take is joined to it from the first word of the
first kept shot (--from; default: the shot where line 2 starts, the 2nd shot when line 1 is one shot),
cut in the silence before that word, never inside it. The pause at the join is the voiceover's own
pause there, and the take's level is matched to the voiceover's. Writes:
    audio/vo_hook<letter>.mp3        the hook line + the voiceover from the cut on
    inputs/script_hook<letter>.txt   the hook line + the script from that word on
    words_hook<letter>.json          its word timings (transcribe.py --script ... --no-draft --words-out)
    shots_hook<letter>.json          a placeholder shot h<letter>01 for the hook line, then every kept shot
                                     moved by the same amount, ids unchanged (so their clips are reused),
                                     with the main plan's music, captions, end card, platform...
Then fill h<letter>01's visual (split it into h<letter>01, h<letter>02... for more shots) and cut it:
generate.py clips . --shots shots_hook<letter>.json, edit.py . --shots shots_hook<letter>.json, verify_vo.py .
The hook line's words (for its captions): --line, else inputs/hook_<letter>.txt, else as Whisper hears the take.
An existing shots_hook<letter>.json is kept unless --force: then its own hook shots are kept, re-timed.
"""
import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CLIP_TYPES, clip_path, ffmpeg, load_audio, load_json, mmss, run_ffmpeg, voiceover_file

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("project")
ap.add_argument("letter", help="the hook's letter: B, C, ... (A is the main ad)")
ap.add_argument("--line-audio", help="the hook line on its own, made with the main voiceover's voice and settings")
ap.add_argument("--line", help="the hook line's words (default: inputs/hook_<letter>.txt, else as heard in the take)")
ap.add_argument("--from", dest="keep", help="the first main shot the hook keeps (default: where line 2 starts)")
ap.add_argument("--language", type=str.lower, help="the voiceover's language code (default: the main plan's, else en)")
ap.add_argument("--trust-script", action="store_true",
                help="passed to transcribe.py: the voiceover was generated from the script")
ap.add_argument("--force", action="store_true", help="remake an existing shots_hook<letter>.json (its hook shots are kept)")
a = ap.parse_args()

import numpy as np

P = a.project
L = re.sub(r"^hook", "", a.letter, flags=re.I).upper()
if not re.fullmatch(r"[A-Z0-9]{1,4}", L):
    sys.exit(f'"{a.letter}" isn\'t a hook letter: use B, C, D...')
if L == "A":
    sys.exit("Hook A is the main ad (shots.json). Give this hook its own letter: B, C, D...")
hook, hid = f"hook{L}", f"h{L}01"
plan_rel, words_out, script_rel, vo_out = (f"shots_{hook}.json", f"words_{hook}.json",
                                           f"inputs/script_{hook}.txt", f"audio/vo_{hook}.mp3")
plan_path = os.path.join(P, plan_rel)


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def norm(t):
    """Letters and digits only, accents dropped ("Été" -> "ete")."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).casefold()) if c.isalnum())


def ends_sentence(w):
    return w.rstrip("\"'”’»)]").endswith((".", "?", "!", "…"))


# ---------- the main plan, its voiceover and words ----------
if not os.path.exists(os.path.join(P, "shots.json")):
    sys.exit('There is no shots.json here: plan the main ad first ("The shots file" in SKILL.md), then make its hooks '
             "from it (run this from inside the project folder).")
data = load_json(os.path.normpath(os.path.join(P, "shots.json")), "Fix that line and run this again.")
shots = data.get("shots") if isinstance(data, dict) else None
if not isinstance(shots, list) or not shots:
    sys.exit('shots.json has no shots: it needs a "shots" list ("The shots file" in SKILL.md).')
for i, s in enumerate(shots):
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not (number(s.get("start")) and number(s.get("end"))):
        sys.exit(f'Shot {i + 1} in shots.json needs an "id", a "start" and an "end": fix it, then run this again.')
ids = [s["id"] for s in shots]
if hid in ids:
    sys.exit(f"shots.json already has a shot called {hid}, the name this hook's own shot gets. Rename it, or "
             "pick another letter.")
if len(shots) < 2 and not a.line_audio:
    sys.exit("shots.json has one shot, so a hook would replace the whole ad. Split it into a shot per line first.")
if os.path.exists(plan_path) and not a.force:
    sys.exit(f"{plan_rel} already exists. Run again with --force to remake this hook's audio and timing: its own "
             f"hook shots are kept (re-timed) and the old file is saved as {plan_rel}.bak. Or pick another letter.")

vo = voiceover_file(P, data)
if not vo:
    sys.exit(f'shots.json has no voiceover ("vo"): each talking clip speaks its own line, so there is nothing to join. '
             f'Plan this hook by hand: copy shots.json to {plan_rel}, put the hook\'s talking shot first as {hid} '
             f'(its own clip, "use_clip_audio": true), move every later shot by its length and add "words": '
             f'"{words_out}" (edit.py fills it from the clips).')
vo_rel = os.path.relpath(vo, P)
if not os.path.isfile(vo):
    sys.exit(f"The main voiceover {vo_rel} doesn't exist. Put it back, or fix shots.json"
             + (' ("vo").' if data.get("vo") else " (its first avatar shot's \"source\", which is the voiceover too)."))
if os.path.normpath(vo_rel) == os.path.normpath(vo_out):
    sys.exit(f"shots.json's voiceover is {vo_out}, the file this hook would write. Point shots.json at the main "
             "voiceover, or pick another letter.")
words_rel = data.get("words") or "words.json"
timing = f"python3 $S/transcribe.py {vo_rel} . --script inputs/script.txt"
words = load_json(os.path.normpath(os.path.join(P, words_rel)), f"Time the voiceover first: {timing}")
if not isinstance(words, list) or not all(isinstance(w, dict) and number(w.get("s")) and number(w.get("e"))
                                          for w in words):
    sys.exit(f'{words_rel} isn\'t a list of words ({{"w", "s", "e"}}). Time the voiceover again: {timing}')
words = [dict(w, w=str(w.get("w", "")).strip()) for w in words if str(w.get("w", "")).strip()]    # as edit.py
if not words:
    sys.exit(f"{words_rel} has no words in it. Time the voiceover again: {timing}")
probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", vo], capture_output=True, text=True, encoding="utf-8",
                       errors="replace").stderr
m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
vo_len = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
if words[-1]["e"] > vo_len + 0.5:
    sys.exit(f"{words_rel} ends at {words[-1]['e']:.1f}s but {vo_rel} is {vo_len:.1f}s long: it was made from another "
             f"take, so the cut would land in the wrong place. Time this voiceover again first: {timing}")
lang = a.language or data.get("language")


# ---------- the first kept shot and its first word ----------
def first_word(shot):
    """The first word mostly inside the shot, or None."""
    return next((k for k, w in enumerate(words) if (w["s"] + w["e"]) / 2 >= shot["start"]), None)


if a.keep:
    if a.keep not in ids:
        sys.exit(f"There's no shot {a.keep} in shots.json (its shots: {', '.join(ids)}).")
    ki = ids.index(a.keep)
    if ki == 0 and not a.line_audio:
        sys.exit(f"--from {a.keep} keeps the whole ad: with no new line there is nothing for the hook to replace.")
else:       # the shot where line 2 starts; the 2nd shot when no shot starts on a sentence
    ki = next((i for i in range(1, len(shots)) if (first_word(shots[i]) or 0) > 0
               and ends_sentence(words[first_word(shots[i]) - 1]["w"])), 1 if len(shots) > 1 else 0)
kept = shots[ki]
k = first_word(kept)
if k is None:
    sys.exit(f"{words_rel} has no words after {kept['id']} starts ({kept['start']}s): check that it belongs to this "
             f"shots.json, or pick the first shot to keep with --from.")
if k > 0 and not ends_sentence(words[k - 1]["w"]):
    print(f'NOTE {kept["id"]} starts mid-sentence ("... {words[k - 1]["w"]} | {words[k]["w"]} ..."): the hook line runs '
          f"straight into it. Check that the two read well together, or keep from the shot where line 2 starts "
          f"(--from).")
said = (kept.get("text") or "").split()
if kept.get("type") != "text" and said and norm(said[0]) and norm(said[0]) != norm(words[k]["w"]):
    print(f'NOTE {kept["id"]}\'s line starts "{said[0]}", but {words_rel} has "{words[k]["w"]}" at {words[k]["s"]:.2f}s: '
          f"check that shots.json and {words_rel} belong together.")
replaced = shots[:ki]
old_text = " ".join(str(s.get("text") or "") for s in replaced).strip()


def placeholder(end, line):
    """The hook's own shot, in the main ad's kind (its first shot's type), to be filled."""
    t = shots[0].get("type", "clip")
    ph = {"id": hid, "start": 0.0, "end": end, "text": line}
    if t == "text":         # a text-card ad: the hook line on a card is the whole shot
        ph.update(type="text", bg=shots[0].get("bg", "#111111"))
        todo = "it's a text card with the hook line: change its words or \"bg\" if you like"
    elif t in ("library", "footage"):
        ph.update(type="library", source="", visual="")
        todo = 'pick its library clip (library.py list <folder>) and set "source": "<folder>/<clip>" (and "in")'
    elif t == "image":
        ph.update(type="image", source="", visual="")
        todo = 'set "source" to its picture'
    else:
        ph.update(type="clip", visual="", frame=f"frames/{hid}.png", video_prompt="")
        todo = (f'write its "visual" and "video_prompt", make frames/{hid}.png (Step 7), then '
                f"python3 $S/generate.py clips . --shots {plan_rel}")
    return ph, todo


def write_plan(new_shots, extra):
    new = {key: copy.deepcopy(v) for key, v in data.items() if key != "shots"}
    new.update(extra)
    if lang:
        new["language"] = lang
    new["shots"] = new_shots
    if os.path.exists(plan_path):
        os.replace(plan_path, plan_path + ".bak")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write("\n")


def keep_old_hook_shots(end, line):
    """With --force: the hook shots of the old shots_hook file (before its first main shot), re-timed to 0..end."""
    try:
        with open(plan_path, encoding="utf-8-sig") as f:
            old = json.load(f).get("shots") or []
    except (OSError, ValueError, AttributeError):
        return []
    lead = []
    for s in old:
        if not isinstance(s, dict) or s.get("id") in ids or not (number(s.get("start")) and number(s.get("end"))):
            break
        lead.append(copy.deepcopy(s))
    if not lead or lead[-1]["end"] <= 0:
        return []
    scale = end / lead[-1]["end"]
    for s in lead:
        s["start"], s["end"] = round(s["start"] * scale, 2), round(s["end"] * scale, 2)
    lead[0]["start"], lead[-1]["end"] = 0.0, end
    if len(lead) == 1:
        lead[0]["text"] = line      # one hook shot says the whole (maybe new) line
    return lead


def unfilled(s):
    """A hook shot with no picture yet (a text card always has one)."""
    t = s.get("type", "clip")
    if t in CLIP_TYPES:
        return not os.path.exists(clip_path(P, s)) and not (s.get("frame") and os.path.exists(os.path.join(P, s["frame"])))
    return t != "text" and not s.get("source") and not s.get("clip")


def next_steps(ph, todo, lead, end):
    if lead:
        print(f"Kept your hook shots {', '.join(s['id'] for s in lead)} from the old {plan_rel}, re-timed to "
              f"0.00-{end:.2f}s (the old file is {plan_rel}.bak).")
    empty = [s["id"] for s in lead or [ph] if unfilled(s)]
    if empty:
        print(f"Next: fill {', '.join(empty)} (0.00-{end:.2f}s): {todo},")
    else:
        print("Next: check that they still fit the hook line," if lead else f"Next: {hid} (0.00-{end:.2f}s): {todo},")
    print(f"then python3 $S/edit.py . --shots {plan_rel}, python3 $S/verify_vo.py . and "
          f"python3 $S/shot_map.py . final/<the new file>.")


# ---------- same opening line, new visuals: no new audio ----------
if not a.line_audio:
    ph, todo = placeholder(kept["start"], old_text)
    lead = keep_old_hook_shots(kept["start"], old_text) if a.force else []
    write_plan((lead or [ph]) + copy.deepcopy(shots[ki:]), {"vo": vo_rel, "words": words_rel})
    print(f"hook {L}: same opening line and voiceover ({vo_rel}), new visuals for "
          f"{', '.join(s['id'] for s in replaced)}; {kept['id']} to {shots[-1]['id']} are the main ad's shots, unchanged.")
    print(f"wrote {plan_rel}")
    next_steps(ph, todo, lead, kept["start"])
    sys.exit(0)


# ---------- the hook line take ----------
line = a.line
own = os.path.join(P, "inputs", f"hook_{L}.txt")
if not line and os.path.exists(own):
    with open(own, encoding="utf-8-sig") as f:
        line = " ".join(f.read().split())
if line is not None and not norm(line):
    sys.exit(f'{"--line" if a.line is not None else f"inputs/hook_{L}.txt"} has no words in it: give the hook line as '
             'it is spoken, e.g. --line "Three a.m. again?"')
line_path = os.path.join(P, a.line_audio) if os.path.exists(os.path.join(P, a.line_audio)) else a.line_audio
if not os.path.isfile(line_path):
    sys.exit(f"No hook line take at {a.line_audio}. Make it with the main voiceover's voice first: python3 "
             f"$S/generate.py voice --text-file inputs/hook_{L}.txt --out audio/{hook}_line.mp3 --voice <its voice id>")
if os.path.abspath(line_path) in (os.path.abspath(vo), os.path.abspath(os.path.join(P, vo_out))):
    sys.exit(f"--line-audio is {a.line_audio}: give the hook line take on its own (e.g. audio/{hook}_line.mp3), not "
             "a full voiceover.")
m = re.search(r"Audio:.*?(\d+) Hz", probe)
rate = int(m.group(1)) if m else 44100
main = load_audio(vo, rate)
take = load_audio(line_path, rate)
hop = rate // 100        # 10 ms frames


def levels(x):
    n = len(x) // hop
    return np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) if n else np.zeros(0)


def quiet_level(lev):
    """Below this a 10 ms frame is silence: 30 dB under the loud speech, or well over the room noise of a take
    recorded with some (3x its quietest frames, at most 20 dB under the loud speech)."""
    if not len(lev):
        return 1e-4
    loud, floor = np.percentile(lev, [95, 10])
    return max(float(loud) * 0.03, min(float(floor) * 3, float(loud) * 0.1), 1e-4)


mlev, tlev = levels(main), levels(take)
mq, tq = quiet_level(mlev), quiet_level(tlev)
talk = np.flatnonzero(tlev >= tq)
if not len(talk):
    sys.exit(f"No speech heard in {a.line_audio}: check that it's the hook line take.")

# The cut: the middle of the silence before the first kept word (Whisper's word times are only roughly right,
# so the silence is found in the sound itself). The pause before the cut is kept on the end of the hook line.
ks = words[k]["s"]
if k == 0:              # the hook goes in front of line 1: all of the voiceover is kept, after a sentence pause
    cut, pause, warn = 0.0, max(0.05, 0.4 - ks), None
else:
    pe = words[k - 1]["e"]
    lo, hi = min(pe, ks), max(pe, ks)
    mid = (lo + hi) / 2
    f0, f1 = max(0, int(min(lo, mid - 0.05) * 100)), min(len(mlev), int(max(hi, mid + 0.05) * 100) + 1)
    runs, r0 = [], None
    for f in range(f0, f1 + 1):
        if f < f1 and mlev[f] < mq:
            r0 = f if r0 is None else r0
        elif r0 is not None:
            runs.append((r0, f))
            r0 = None
    if runs:
        r0, r1 = max(runs, key=lambda r: (r[1] - r[0], -abs((r[0] + r[1]) / 200 - mid)))
        while r0 > 0 and mlev[r0 - 1] < mq and (r0 - 1) / 100 > words[k - 1]["s"]:     # the whole silence
            r0 -= 1
        while r1 < len(mlev) and mlev[r1] < mq and r1 / 100 < words[k]["e"]:
            r1 += 1
        cut, pause = (r0 + r1) / 200, (r1 - r0) / 200
        warn = (f'only {(r1 - r0) * 10} ms of silence between "{words[k - 1]["w"]}" and "{words[k]["w"]}" at '
                f"{ks:.2f}s") if r1 - r0 < 10 else None
    else:
        f = f0 + int(np.argmin(mlev[f0:f1])) if f1 > f0 else int(mid * 100)
        cut, pause = (f + 0.5) / 100, max(0.05, (f + 0.5) / 100 - pe)
        warn = f'no silence between "{words[k - 1]["w"]}" and "{words[k]["w"]}" at {ks:.2f}s'
if warn:
    print(f"WARNING {warn}: the join may clip a word. Listen to {vo_out} at the join; if it does, keep from a shot "
          "that starts after a pause (--from).")

# The take: its own silence in front trimmed to the voiceover's (the first word comes as fast as in the main
# ad), its end followed by the voiceover's pause, and its level matched to the voiceover's speech.
mtalk = np.flatnonzero(mlev >= mq)
lead_main = min(max(mtalk[0] / 100 if len(mtalk) else 0.1, 0.05), 0.3)
head = max(0, int((talk[0] / 100 - min(talk[0] / 100, lead_main)) * rate))
end = (talk[-1] + 1) * hop + int(pause * rate)
part = take[head:end]
if len(part) < end - head:
    part = np.concatenate([part, np.zeros(end - head - len(part), np.float32)])
gain = np.sqrt(np.mean(mlev[mtalk] ** 2)) / np.sqrt(np.mean(tlev[talk] ** 2))
db = 20 * np.log10(gain)
if abs(db) > 1.5:
    peak = float(np.abs(part).max()) or 1.0
    gain = min(gain, 0.97 / peak)       # never clip
    part = part * gain
    print(f"matched the hook line's level to the voiceover ({20 * np.log10(gain):+.1f} dB)")
cut_i = int(round(cut * rate))
body = main[cut_i:].copy()
n = min(len(body), int(0.005 * rate))   # 5 ms fades at the join: no click even if the cut isn't silent
body[:n] *= np.linspace(0, 1, n, dtype=np.float32)
part[len(part) - n:] *= np.linspace(1, 0, n, dtype=np.float32)
joined = np.concatenate([part, body])
delta = (len(part) - cut_i) / rate
join_t = len(part) / rate

os.makedirs(os.path.join(P, "audio"), exist_ok=True)
fd, tmp = tempfile.mkstemp(suffix=".wav")
os.close(fd)
try:
    with wave.open(tmp, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(joined, -1, 1) * 32767).astype("<i2").tobytes())
    run_ffmpeg(["-i", tmp, "-c:a", "libmp3lame", "-q:a", "2", os.path.join(P, vo_out)])
finally:
    os.remove(tmp)

# ---------- the hook line's words and the hook's script ----------
if not line:
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en" if lang in (None, "en") else "small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(load_audio(line_path), language=lang, vad_filter=False)
    line = " ".join(s.text.strip() for s in segs).strip()
    if not norm(line):
        sys.exit(f"No words heard in {a.line_audio}. Give the hook line with --line \"...\".")
    print(f"The hook line, as heard in the take: {line}\nThe captions show these words: if one is wrong (a brand "
          f'name), run this again with --line "<the right words>" --force.')
os.makedirs(os.path.join(P, "inputs"), exist_ok=True)
with open(os.path.join(P, script_rel), "w", encoding="utf-8") as f:
    f.write(line + "\n" + " ".join(w["w"] for w in words[k:]) + "\n")

cmd = [sys.executable, os.path.join(HERE, "transcribe.py"), os.path.join(P, vo_out), P, "--script",
       os.path.join(P, script_rel), "--no-draft", "--words-out", words_out]
cmd += (["--language", lang] if lang else []) + (["--trust-script"] if a.trust_script else [])
print(f"timing {vo_out} (transcribe.py):")
sys.stdout.flush()
if subprocess.run(cmd).returncode:
    sys.exit(f"transcribe.py stopped (its message is above), so {plan_rel} wasn't written. {vo_out} and {script_rel} "
             "are there to listen to and read: fix the cause, then run hook.py again"
             + (" with --force." if os.path.exists(plan_path) else "."))

# The join, heard: a word clipped there is heard differently (or not at all). The timing needs no check: the
# kept part of the voiceover moved by exactly delta. (transcribe.py above already listed the line's own words.)
new_words = [w for w in load_json(os.path.join(P, words_out)) if isinstance(w, dict) and number(w.get("s"))]
odd = [w for w in new_words if "heard" in w and norm(w["heard"]) != norm(w.get("w", "")) and abs(w["s"] - join_t) <= 1]
if not any(norm(w.get("w", "")) == norm(words[k]["w"]) and abs(w["s"] - (ks + delta)) < 1 for w in new_words):
    odd.append({"s": ks + delta, "heard": "nothing", "w": words[k]["w"]})
if any(w.get("heard") == w.get("w") for w in new_words):
    print(f"(hook.py ran transcribe.py for you: fix those words in {words_out} by hand, or, when the hook line take "
          "and the voiceover were both generated from the script, run hook.py again with --trust-script --force.)")
if odd:
    print(f"WARNING at the join ({join_t:.2f}s), {vo_out} doesn't sound like the script:")
    for w in odd:
        print(f'  {w["s"]:.2f}s  heard "{w["heard"]}", the script says "{w["w"]}"')
    print(f"Listen to {vo_out} around {mmss(join_t)}. If a word is clipped, keep from a shot that starts after a pause "
          f"(--from) and run this again with --force.")

# ---------- the hook's plan: its own shot, then every kept shot moved by delta ----------
trim = max(0.0, cut - kept["start"])        # a kept shot that started before the cut starts at the join
first = round(max(kept["start"], cut) + delta, 2)
moved = copy.deepcopy(shots[ki:])
for i, s in enumerate(moved):
    if s.get("type") in ("avatar", "footage") and "in" not in s:
        s["in"] = shots[ki + i]["start"]    # an avatar video stays in sync with the voiceover it speaks
    if i == 0 and trim and (number(s.get("in")) or s.get("type") in ("avatar", "footage")):
        s["in"] = round(s.get("in", 0) + trim, 2)
    s["start"], s["end"] = (first if i == 0 else round(s["start"] + delta, 2)), round(s["end"] + delta, 2)
ph, todo = placeholder(first, line)
lead = keep_old_hook_shots(first, line) if a.force else []
extra = {"vo": vo_out, "words": words_out}
music = data.get("music")
if isinstance(music, dict) and number(music.get("switch_at")) and music["switch_at"] >= cut:
    extra["music"] = dict(music, switch_at=round(music["switch_at"] + delta, 2))
write_plan((lead or [ph]) + moved, extra)

gone = ", ".join(s["id"] for s in replaced)
print(f'\nhook {L}: "{line}" ({join_t:.2f}s with its pause) '
      + (f"replaces {gone} (0.00-{kept['start']:.2f}s)" if replaced else "goes in front of the whole ad"))
print(f'{vo_out}: the hook line + {vo_rel} from {cut:.2f}s ("{words[k]["w"]} ...") = {len(joined) / rate:.1f}s '
      f"({vo_rel} is unchanged)")
print(f"{kept['id']} to {shots[-1]['id']} move by {delta:+.2f}s, ids unchanged, so their clips are reused")
print(f"wrote {script_rel}, {words_out}, {plan_rel}")
next_steps(ph, todo, lead, first)
