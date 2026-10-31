"""Check finished ads against the voiceover. Run on EVERY final before it goes to anyone.

    verify_vo.py <project> [final/ad1.mp4 ...] [--shots shots.json] [--language fr]

With no files, the newest version of every 9:16 final in <project>/final/ is checked (previews, older
_v<n> takes and the 4x5 / 1x1 / 16x9 sizes, which carry their 9:16's sound, skipped). Files can be given
from the project folder (final/ad1.mp4) or from the working folder (<project>/final/ad1.mp4).
Each file is checked against the plan it was cut from: <project>_hookB_... -> shots_hookB.json,
anything else -> shots.json (--shots forces one plan for every file).
Three checks per file with a voiceover:
  1. Waveform: every half second of the voiceover is in the final at the same moment (within 20ms).
     This catches dropped chunks, gaps and drift that a listen-through misses.
  2. Words: the final is transcribed and every word of the words file must be there, in order
     (as Whisper heard it in the voiceover, or as the script spells it, so a brand name it mishears
     doesn't count as missing). When the waveform check passes, a word the final is heard saying
     differently is checked against the voiceover itself: the words file must be the voiceover's.
  3. Captions in sync: each word is heard in the final when the words file says (the captions are cut
     from it), so a words file left over from another voiceover take fails, and so does one from a shorter
     take (words heard in the voiceover after its last word; sound with no words in it, a music bed or room
     tone, is only noted). A word with nothing heard for it ("heard": "") needs the voiceover to make a
     sound under it, or the captions show a word nobody says.
Prints PASS or FAIL for each file; exits 1 if any file fails.
For ads with no voiceover file where the video tool's own voices speak ("use_clip_audio"), each talking
shot's line (its "text", the approved script) must be heard inside that shot: a line cut off by its slot,
changed or missing fails, named by shot id. Ads with no voice at all (no voiceover, avatar or clip voice,
e.g. text cards) have no speech to check and pass.
Not in English: set "language" in the shots file (e.g. "fr") or pass --language; the multilingual
Whisper model is used instead of the English-only one.
"""
import argparse
import difflib
import glob
import json
import os
import re
import shlex
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clip_path, load_audio

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("finals", nargs="*", help="default: every final in <project>/final/")
ap.add_argument("--shots", help="force one shots file for every file (default: matched by hook name)")
ap.add_argument("--words", help="default: the shots file's words, else words.json")
ap.add_argument("--vo", help="voiceover to compare against (default: the shots file's vo)")
ap.add_argument("--language", type=str.lower,
                help="the voiceover's language code, e.g. fr (default: the shots file's, else en)")
ap.add_argument("--model", help="Whisper model (default: small.en for English, else small)")
a = ap.parse_args()
sys.stdout.reconfigure(errors="replace")                 # accented words print even on a non-UTF-8 console

import numpy as np
from faster_whisper import WhisperModel

finals = []
for f in a.finals or [os.path.join("final", "*.mp4")]:
    cand = os.path.join(a.project, f)
    if os.path.exists(cand) or os.path.exists(f):     # from the project folder, else from the working folder
        finals.append(cand if os.path.exists(cand) else f)
        continue
    # only the file part is a pattern: a folder named "Ad [v2]" is a name, not a set of letters
    found = sorted(p for p in glob.glob(os.path.join(glob.escape(a.project), f)) or glob.glob(f)
                   if not os.path.basename(p).startswith("preview_"))
    if not found:
        sys.exit(f"No file matches {f} (give it from the project folder or from the working folder).")
    finals += found
if not a.finals:              # by default only the newest take of each final: older _v<n> files are kept for history
    newest = {}
    for p in finals:
        m = re.match(r"(.*)_v(\d+)\.mp4$", os.path.basename(p))
        key, n = (m.group(1), int(m.group(2))) if m else (p, 0)
        if key not in newest or n > newest[key][0]:
            newest[key] = (n, p)
    finals = sorted(p for _, p in newest.values())
    # The 4x5 / 1x1 / 16x9 files carry their 9:16's sound untouched (variants.py copies it), so hearing them again
    # proves nothing, and a size not made again yet from a new cut would fail for the wrong reason.
    sizes = [p for p in finals if re.search(r"_(4x5|1x1|16x9)_", os.path.basename(p))]
    if sizes and len(sizes) < len(finals):
        finals = [p for p in finals if p not in sizes]
        print(f"({len(sizes)} 4x5/1x1/16x9 file(s) not checked: they have their 9:16's sound, and qc.py checks each "
              "was made from the newest 9:16)")


def norm(t):
    """Letters and digits only, accents dropped ("Été" -> "ete")."""
    return "".join(c for c in unicodedata.normalize("NFKD", t.casefold()) if c.isalnum())


def plan_for(name):
    """The plan a final was cut from: <project>_hookB_... -> shots_hookB.json, hookA -> shots.json (as qc.py)."""
    rel = a.shots
    if not rel:
        m = re.search(r"_(hook\w+?)_(?:9x16|4x5|1x1|16x9)_", name)
        rel = f"shots_{m.group(1)}.json" if m and os.path.exists(os.path.join(a.project, f"shots_{m.group(1)}.json")) \
            else "shots.json"
    path = os.path.join(a.project, rel)
    if not os.path.exists(path):
        return rel, {}
    try:
        with open(path, encoding="utf-8") as f:
            return rel, json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        return rel, f"{rel} can't be read ({e}): fix it and run this again."


def speaks(data):
    """As qc.py: the ad has a voice when it has a voiceover, an avatar or a clip that keeps its own voice."""
    return bool(data.get("vo")) or any(s.get("use_clip_audio") or s.get("type") == "avatar"
                                       for s in data.get("shots") or [])


plans, models = {}, {}


def load_plan(rel, data):
    """What a plan's finals are checked against: a dict, None if nothing is spoken, or the reason it can't be."""
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return f"{rel} isn't a shots file (it should hold {{\"shots\": [...]}}): fix it and run this again."
    if not data and not a.vo:
        return f"{rel} isn't in {a.project}: give the plan this file was cut from with --shots."
    vo_rel = a.vo or data.get("vo") or next((s["source"] for s in data.get("shots", [])      # as edit.py: an avatar
                                              if s.get("type") == "avatar" and s.get("source")), None)  # video is the VO
    words_rel = a.words or data.get("words")
    hook = re.match(r"shots_(hook.*)\.json$", os.path.basename(rel))
    own = f"words_{hook.group(1)}.json" if hook else None
    try:
        with open(os.path.join(a.project, "shots.json"), encoding="utf-8") as f:
            main_vo = json.load(f).get("vo")
    except (OSError, ValueError, AttributeError):
        main_vo = None
    # a hook with its own voiceover is timed into its own words file (as edit.py and hook.py do)
    own_vo = bool(hook) and (not vo_rel or os.path.normpath(vo_rel) != os.path.normpath(str(main_vo or "")))
    if not words_rel and hook and (os.path.exists(os.path.join(a.project, own)) or own_vo):
        words_rel = own
    words_rel = words_rel or "words.json"
    wp = os.path.join(a.project, words_rel)
    lang = (a.language or data.get("language") or "en").lower()
    if data.get("shots") and not vo_rel and not speaks(data):
        # Nothing is spoken (option 5, text cards and stills), unless the voiceover was left out of the plan.
        try:
            with open(wp, encoding="utf-8") as f:
                left = bool(json.load(f))
        except (OSError, ValueError, UnicodeDecodeError):
            left = False
        if left:
            return (f"{words_rel} is there but {rel} has no \"vo\": the ad was cut without its voiceover. Add "
                    f"\"vo\": \"audio/vo.mp3\" to {rel} and run edit.py again (or, if this ad has no voice on "
                    f"purpose, delete {words_rel}).")
        return None
    if not vo_rel:
        # The video tool's own voices: the reference is each talking shot's line, not words.json, which edit.py
        # transcribes from this very sound (comparing with it would prove nothing).
        talk = [s for s in data.get("shots") or [] if s.get("use_clip_audio")]
        odd = [str(s.get("id", "?")) for s in talk if not all(isinstance(s.get(k), (int, float)) for k in ("start", "end"))]
        if odd:
            return f"{', '.join(odd)} in {rel} need a \"start\" and an \"end\" (seconds): fix the plan and edit again."
        return {"talk": talk, "lang": lang}
    vp = os.path.join(a.project, vo_rel)
    if not os.path.exists(vp):
        return f"The voiceover {vp} (from {'--vo' if a.vo else rel}) doesn't exist."
    vo = load_audio(vp, 8000)
    if len(vo) < 8000:
        return f"The voiceover {vp} has less than a second of sound."
    # The fix always times a hook's own voiceover into the hook's own words file, never over the main words.json.
    target = own if own_vo else words_rel
    m = re.match(r"words_(.+)\.json$", os.path.basename(target))          # words_hookB.json <- script_hookB.txt
    script = os.path.join(a.project, "inputs", f"script_{m.group(1)}.txt" if m else "script.txt")
    q = shlex.quote             # a space or a bracket in a folder name still pastes as one argument
    redo = (f"python3 $S/transcribe.py {q(os.path.normpath(vp))} {q(a.project)} --script "
            + (q(os.path.normpath(script)) if os.path.exists(script) else "<its script>")
            + (f" --language {lang}" if lang != "en" else "")
            + (f" --words-out {q(target)} --no-draft" if target != "words.json" else ""))
    if not a.words and data.get("words") != target and target != "words.json":
        redo += f', and set "words": "{target}" in {rel}'
    if not os.path.exists(wp):
        return f"No word timings at {wp}: time the voiceover first ({redo}), then run edit.py again."
    try:
        with open(wp, encoding="utf-8") as f:
            ref = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        return f"{wp} can't be read ({e}): fix it, or time the voiceover again ({redo})."
    if not isinstance(ref, list) or not all(isinstance(w, dict) and "w" in w and isinstance(w.get("s"), (int, float))
                                            for w in ref):
        return f"{wp} isn't a words file (a list of {{\"w\", \"s\", \"e\"}}): time the voiceover again ({redo})."
    # What Whisper heard where transcribe.py took the script's spelling: the final is heard the same way.
    # Words with no letters (a dash, an emoji) can never be heard, so they don't count.
    tok = [(norm(x), i) for i, w in enumerate(ref) for x in str(w.get("heard", w["w"])).split() if norm(x)]
    if not tok:
        return f"{wp} has no words in it, so the ad has no captions: time the voiceover again ({redo})."
    # A word added with nothing heard for it ("heard": "") isn't looked for in the final, so at least the voiceover
    # must make a sound there: one placed past the voice's end (or in a pause) is a caption nobody says.
    mute, k = [], 0
    while k < len(ref):
        if ref[k].get("heard") != "" or not norm(str(ref[k]["w"])):
            k += 1
            continue
        j = k
        while j + 1 < len(ref) and ref[j + 1].get("heard") == "":
            j += 1
        first = k - 1 if k and ref[k - 1].get("heard") else k   # a word spread over what was heard just before
        s0, s1 = float(ref[first]["s"]), float(ref[j].get("e", ref[j]["s"]))
        steps = np.arange(s0, max(s1, s0 + 0.05), 0.01)
        loud = sum(np.abs(vo[int(t * 8000):int(t * 8000) + 80]).max(initial=0) >= 300 / 32768 for t in steps)
        if loud < len(steps) / 2:      # a word is mostly sound; the tail of the word before is short
            mute.append((k, j))
        k = j + 1
    return {"vo": vo, "vp": vp, "vo_rel": vo_rel, "words": words_rel, "redo": redo, "ref": ref, "tok": tok,
            "lang": lang, "mute": mute}


def hear(path, lang):
    """The words Whisper hears in a file: (letters only, start second, as heard)."""
    name = a.model or ("small.en" if lang == "en" else "small")
    if name not in models:
        models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    segs, _ = models[name].transcribe(load_audio(path), language=lang, word_timestamps=True)
    return [(norm(w.word), w.start, w.word.strip()) for s in segs for w in s.words if norm(w.word)]


def as_written(ref, tok, i1, i2, got_part):
    """True if the final has these words as the script spells them (a hand-fixed "w"), not as Whisper heard
    them in the voiceover: the final, with music under it, is sometimes heard better than the voiceover alone."""
    entries = sorted({tok[k][1] for k in range(i1, i2)})
    written, heard = "".join(norm(ref[e]["w"]) for e in entries), "".join(got_part)
    return bool(written) and difflib.SequenceMatcher(None, written, heard).ratio() >= 0.85


def align(plan, got):
    """Line the words file up with the words heard: (words in place, [(i1, i2, j1, j2)] not in place,
    [(word, heard)] index pairs that line up one for one)."""
    tok, ref = plan["tok"], plan["ref"]
    want, heard = [t for t, _ in tok], [g[0] for g in got]
    matched, missing, pairs = 0, [], []
    for kind, i1, i2, j1, j2 in difflib.SequenceMatcher(None, want, heard, autojunk=False).get_opcodes():
        # the same words heard a little differently ("quizre" in the voiceover, "quizra" in the final) are there
        if kind == "equal" or kind == "replace" and i2 - i1 == j2 - j1 and all(
                difflib.SequenceMatcher(None, want[i1 + k], heard[j1 + k]).ratio() >= 0.75 for k in range(i2 - i1)):
            matched += i2 - i1
            pairs += [(i1 + k, j1 + k) for k in range(i2 - i1)]
        elif kind == "replace" and (as_written(ref, tok, i1, i2, heard[j1:j2]) or difflib.SequenceMatcher(
                None, "".join(want[i1:i2]), "".join(heard[j1:j2])).ratio() >= 0.85):    # "wrist well" -> "wristwell"
            matched += i2 - i1
        elif kind in ("delete", "replace"):
            missing.append((i1, i2, j1, j2))
    return matched, missing, pairs


def waveform_check(vo, path, music):
    fin, errs = load_audio(path, 8000), []
    for t in np.arange(0, len(vo) / 8000 - 0.5, 0.5):    # back to back half-second windows
        i = int(t * 8000)
        n = min(4000, len(fin) - i)                       # a final a few ms short still has its last window checked
        if n < 2000:
            errs.append(f"{t:.1f}s (the final's sound ends at {len(fin) / 8000:.2f}s)")
            break
        w = vo[i:i + n]
        if np.abs(w).max() < 300 / 32768:
            continue          # silence: nothing to match
        best = (-1, 0)
        # From 0 outward, and only a clearly better match moves it: a music bed in the voiceover matches as
        # well one beat early or late, which isn't a shift.
        for lag in sorted(range(-1600, 1601, 40), key=abs):
            j = i + lag
            if j < 0 or j + n > len(fin):
                continue
            seg = fin[j:j + n]
            c = float(np.dot(w, seg) / (np.linalg.norm(w) * np.linalg.norm(seg) + 1e-9))
            if c > best[0] + 0.05:
                best = (c, lag / 8000)
        # music under the voice lowers the match a little; a dropped or shifted chunk drops it a lot
        if best[0] < (0.7 if music else 0.85) or abs(best[1]) > 0.02:
            errs.append(f"{t:.1f}s (match {best[0]:.2f}, offset {best[1] * 1000:+.0f}ms)")
    return errs


def drift_check(plan, got, pairs):
    """Why the captions are out of sync with the final, or None. Each word's start in the words file against
    when the final is heard saying it: the same within a few hundredths of a second when the file is right."""
    tok, ref = plan["tok"], plan["ref"]
    # the first word heard of each entry starts when the entry does
    drift = sorted(got[j][1] - ref[tok[i][1]]["s"] for i, j in pairs if i == 0 or tok[i - 1][1] != tok[i][1])
    if len(drift) < 10:
        return None
    off = sorted(abs(d) for d in drift)
    if off[len(off) // 2] <= 0.3 and sum(d > 0.5 for d in off) <= 0.1 * len(off):
        return None
    med = drift[len(drift) // 2]
    return (f"captions are out of sync: {plan['words']} wasn't made from this voiceover (its words are heard "
            f"{abs(med):.1f}s {'later' if med > 0 else 'earlier'} than it says, up to {off[-1]:.1f}s)")


def check_lines(plan, got):
    """Talking-characters route: (ok, words heard in place, words in the lines, lines to print). Each talking
    shot's line must be heard inside its own slot (half a second either side for Whisper's timing)."""
    talk = plan["talk"]
    want = [(norm(x), x, n) for n, s in enumerate(talk)                     # [audio tags] aren't spoken
            for x in re.sub(r"\[[^\]]*\]", " ", str(s.get("text") or "")).split() if norm(x)]
    if not want:
        if not got:
            return True, 0, 0, ["(no speech heard, and no talking shot has a line in \"text\")"]
        ids = ", ".join(s.get("id", "?") for s in talk)
        return False, 0, 0, [f"{ids} keep their clip's voice but have no line in \"text\": write each talking shot's "
                             "spoken line in its \"text\" so the words can be checked, then run this again."]
    heard = [g[0] for g in got]
    inplace, instead = [False] * len(want), {}
    for kind, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [w[0] for w in want], heard,
                                                         autojunk=False).get_opcodes():
        if kind == "insert":
            continue
        # the same words heard a little differently, one for one or as one run of letters ("Brew Haus" heard as
        # "brew house"), are there
        near = kind == "equal" or kind == "replace" and (i2 - i1 == j2 - j1 and all(
            difflib.SequenceMatcher(None, want[i1 + k][0], heard[j1 + k]).ratio() >= 0.75 for k in range(i2 - i1))
            or difflib.SequenceMatcher(None, "".join(w[0] for w in want[i1:i2]),
                                       "".join(heard[j1:j2])).ratio() >= 0.8)
        if near:
            for k in range(i2 - i1):
                j = j1 + min(k * (j2 - j1) // (i2 - i1), j2 - j1 - 1)
                s = talk[want[i1 + k][2]]
                inplace[i1 + k] = s["start"] - 0.5 <= got[j][1] <= s["end"] + 0.5
        elif kind == "replace":
            instead[i1] = " ".join(g[2] for g in got[j1:j2])
    ok, out = True, []
    for n, s in enumerate(talk):
        idx = [k for k, w in enumerate(want) if w[2] == n]
        here = [g for g in got if s["start"] - 0.5 <= g[1] <= s["end"] + 0.5]
        if not idx:
            if here:            # it talks, but there's no line to check it against
                ok = False
                out.append(f"{s.get('id', '?')} ({s['start']:.1f}-{s['end']:.1f}s): speech heard (\""
                           + " ".join(g[2] for g in here[:10]) + "\") but it has no line in \"text\": write its "
                           "spoken line there so it can be checked, then run this again.")
            continue
        # The match above is one pass over the whole ad, so a missing line next door can pull this shot's words
        # out of place: match the line again against only what's heard inside this shot's own slot.
        mine, near_here = [want[k][0] for k in idx], [g[0] for g in here]
        for kind, i1, i2, j1, j2 in difflib.SequenceMatcher(None, mine, near_here, autojunk=False).get_opcodes():
            if kind == "equal" or kind == "replace" and (i2 - i1 == j2 - j1 and all(
                    difflib.SequenceMatcher(None, mine[i1 + q], near_here[j1 + q]).ratio() >= 0.75
                    for q in range(i2 - i1)) or difflib.SequenceMatcher(
                    None, "".join(mine[i1:i2]), "".join(near_here[j1:j2])).ratio() >= 0.8):
                for q in range(i1, i2):
                    inplace[idx[q]] = True
        runs, run = [], []
        for k in idx:
            if not inplace[k]:
                run.append(k)
            elif run:
                runs, run = runs + [run], []
        if run:
            runs.append(run)
        miss = sum(len(r) for r in runs)
        where = f"{s.get('id', '?')} ({s['start']:.1f}-{s['end']:.1f}s)"
        if miss == len(idx):
            ok = False
            clip = clip_path(a.project, s) or os.path.join(a.project, "clips", f"{s.get('id')}.mp4")
            out.append(f"{where}: none of its line was heard: " + (
                f"{clip} doesn't exist, so the shot plays its start frame with no voice. Make the clip"
                if not os.path.exists(clip) else f"is {clip} silent, or saying something else? Listen to it; remake "
                                                 "it if it's wrong") + ", then run edit.py again.")
            continue
        bad = miss >= 2 and miss > 0.1 * len(idx) or max((len(r) for r in runs), default=0) >= 3
        ok = ok and not bad
        for r in runs:
            words = " ".join(want[k][1] for k in r)
            said = " ".join(instead[k] for k in r if k in instead)
            if not bad:
                what = f"heard as \"{said}\"" if said else "not heard"
                out.append(f"{where}: \"{words}\" {what} (listen to that moment: if the clip really says that, "
                           "tell the user)")
            elif r[-1] == idx[-1]:
                out.append(f"{where}: \"{words}\" not heard" + (f" (heard \"{said}\" instead)" if said else "") +
                           ": the end of the line is cut off by the end of the shot, or the clip says something "
                           "else. If the clip is still talking when the shot ends, lengthen the shot (or set a later "
                           "\"in\"); otherwise remake the clip.")
            else:
                out.append(f"{where}: \"{words}\" " + (f"heard as \"{said}\"" if said else "not heard") +
                           ": the clip says something else. Listen to it; remake it if the words are wrong.")
    return ok, sum(inplace), len(want), out


bad = 0
for path in finals:
    name = os.path.basename(path)
    rel, data = plan_for(name)
    if rel not in plans:
        plans[rel] = load_plan(rel, data)
    plan = plans[rel]
    tag = f" ({rel})" if rel != "shots.json" else ""
    if plan is None:
        print(f"PASS  {name}: no speech to check (no voiceover, avatar or clip voice in {rel})")
        continue
    if isinstance(plan, str):
        bad += 1
        print(f"FAIL  {name}: {plan}")
        continue
    got = hear(path, plan["lang"])
    if "talk" in plan:
        ok, matched, total, notes = check_lines(plan, got)
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {matched}/{total} words of the talking shots' lines heard in their "
              f"shots (no voiceover: checked against each talking shot's \"text\"){tag}")
        for n in notes:
            print("      " + n)
        continue
    ref, tok = plan["ref"], plan["tok"]
    matched, missing, pairs = align(plan, got)
    werr = waveform_check(plan["vo"], path, data.get("music"))
    sync = drift_check(plan, got, pairs)
    # With every moment of the voiceover's waveform in place, no word can be missing: a word the final is heard
    # saying differently is Whisper hearing the mixed sound differently, unless the voiceover itself doesn't say
    # it either: then the words file (and the captions cut from it) belongs to another voiceover or take.
    stale = []
    if not werr and missing:
        if "heard" not in plan:
            plan["heard"] = hear(plan["vp"], plan["lang"])
        vo_missing = align(plan, plan["heard"])[1]
        if any(j2 > j1 for _, _, j1, j2 in vo_missing) or sum(i2 - i1 for i1, i2, _, _ in vo_missing) >= 2:
            stale = vo_missing
    # A words file from a shorter take (lines added since, or a cut-off timing run) lines up perfectly as far as it
    # goes: catch the voiceover still talking after its last word (the voice-only file, so music can't do it).
    last = max(float(w.get("e", w["s"])) for w in ref)
    vo = plan["vo"]
    tail = [t for t in np.arange(last + 0.5, len(vo) / 8000 - 0.5, 0.5)
            if np.abs(vo[int(t * 8000):int(t * 8000) + 4000]).max() >= 300 / 32768]
    after = []
    longer = noise = len(tail) >= 3
    if noise:
        # Sound is talking only when words are heard in it: a music bed or room tone in the voiceover file isn't,
        # and timing the voiceover again can't change that.
        if "heard" not in plan:
            plan["heard"] = hear(plan["vp"], plan["lang"])
        after = [g for g in plan["heard"] if g[1] > last + 0.1]       # the next word after the last one
        longer = len(after) >= 2
    mute = plan["mute"]
    ok = not werr and not sync and not stale and not longer and not mute
    bad += not ok
    wave = "identical to the voiceover" if not werr else "MISMATCH"
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {matched}/{len(tok)} words in place, waveform {wave}{tag}")
    for e in werr[:8]:
        print(f"      voiceover missing or shifted at {e}")
    if werr:
        print("      (a music bed inside the voiceover file itself can cause this: if the words are all in place, "
              "listen to that moment)")
    if sync:
        print("      " + sync)
    for i1, i2, j1, j2 in stale[:6]:
        i, j = tok[i1][1], tok[i2 - 1][1] + 1
        says = " ".join(g[2] for g in plan["heard"][j1:j2][:12]) + (" ..." if j2 - j1 > 12 else "")
        print(f"      {plan['words']} doesn't match the voiceover at {ref[i]['s']:.1f}s: it has "
              f"\"{' '.join(str(w['w']) for w in ref[i:j])}\", " +
              (f"the voiceover says \"{says}\"" if says else "the voiceover doesn't say it"))
    if len(stale) > 6:
        print(f"      ... and {len(stale) - 6} more places")
    if longer:
        print(f"      the voiceover goes on talking after {plan['words']} ends at {last:.1f}s (heard \""
              + " ".join(g[2] for g in after[:8]) + ("..." if len(after) > 8 else "") + f"\" from {after[0][1]:.1f}s): "
              "it was timed from a shorter take, so the end has no captions")
    if sync or stale or longer:
        print(f"      The captions come from {plan['words']}: time this voiceover again ({plan['redo']}), "
              "then run edit.py again.")
    for k, j in mute:
        print(f"      {plan['words']} has \"{' '.join(str(w['w']) for w in ref[k:j + 1])}\" at {ref[k]['s']:.1f}s with "
              "nothing heard for it, and the voiceover is silent there: the captions show words nobody says. Listen "
              f"to {plan['vo_rel']} there: if it doesn't say them, delete them from {plan['words']}; if it does, set "
              "their \"s\" and \"e\" to when it says them. Then run edit.py again.")
    if noise and not longer and after and not plan.get("told_bed"):
        plan["told_bed"] = True     # once per plan
        print(f"      note: only \"{after[0][2]}\" is heard in {plan['vo_rel']} after the last word of {plan['words']} "
              f"({after[0][1]:.1f}s, the rest is music or room tone): if the voiceover really says it there, time it "
              f"again ({plan['redo']}) and run edit.py again; if not, it's fine.")
    elif noise and not longer and not plan.get("told_bed"):
        plan["told_bed"] = True     # once per plan
        root, ext = os.path.splitext(plan["vo_rel"])
        print(f"      note: {plan['vo_rel']} has {len(vo) / 8000 - last:.1f}s of sound after its last word "
              f"({last:.1f}s) with no words in it (a music bed or room tone), and the ad plays it: fine if it's meant to "
              f"be there. To end sooner, trim it (ffmpeg -i {shlex.quote(os.path.normpath(plan['vp']))} -t "
              f"{last + 0.5:.1f} {shlex.quote(os.path.normpath(os.path.join(a.project, root + '_trimmed' + ext)))}), "
              f"set \"vo\": \"{root}_trimmed{ext}\" in {rel} and run edit.py again.")
    for i1, i2, _, _ in ([] if stale else missing):
        if i2 - i1 > 2:
            i, j = tok[i1][1], tok[i2 - 1][1] + 1
            what = "heard differently (the waveform shows it's there)" if not werr else "missing or changed"
            print(f"      {what} at {ref[i]['s']:.1f}s: \"{' '.join(str(w['w']) for w in ref[i:j])}\"")
    left = [w for w in ref if w.get("heard") is not None and w.get("heard") == w["w"]]
    if left and not plan.get("told"):
        plan["told"] = True     # once per plan
        print(f"      note: {len(left)} word(s) in {plan['words']} are still as Whisper heard them, not as the script "
              "says, so the captions show them that way: " +
              ", ".join(f"{w['s']:.1f}s \"{w['w']}\"" for w in left[:6]) + (" ..." if len(left) > 6 else "") +
              f". Fix each \"w\" in {plan['words']} (keep \"heard\"), or delete its \"heard\" if the voiceover really "
              "says that, then run edit.py again.")
sys.exit(1 if bad else 0)
