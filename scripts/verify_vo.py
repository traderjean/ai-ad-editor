"""Check finished ads against the voiceover. Run on EVERY final before it goes to anyone.

    verify_vo.py <project> [final/ad1.mp4 ...] [--shots shots.json] [--language fr]

With no files, the newest version of every final in <project>/final/ is checked (previews and older
_v<n> takes skipped). Files can be given
from the project folder (final/ad1.mp4) or from the working folder (<project>/final/ad1.mp4).
Each file is checked against the plan it was cut from: <project>_hookB_... -> shots_hookB.json,
anything else -> shots.json (--shots forces one plan for every file).
Two checks per file:
  1. Waveform: every half second of the voiceover is in the final at the same moment (within 20ms).
     This catches dropped chunks, gaps and drift that a listen-through misses.
  2. Words: the final is transcribed and every word of the words file must be there, in order
     (as Whisper heard it in the voiceover, or as the script spells it, so a brand name it mishears
     doesn't count as missing). When the waveform check passes, word differences are only noted:
     the voiceover is provably all there, and Whisper hears mixed sound a little differently.
Prints PASS or FAIL for each file; exits 1 if any file fails.
For ads with no separate voiceover file (the video tool's own voices) only the word check runs,
against the words file given in the shots file. Text-only ads (every shot a text card) have no speech
to check and pass.
Not in English: set "language" in the shots file (e.g. "fr") or pass --language; the multilingual
Whisper model is used instead of the English-only one.
"""
import argparse
import difflib
import glob
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_audio

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
    found = sorted(p for p in glob.glob(cand) or glob.glob(f) if not os.path.basename(p).startswith("preview_"))
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
    with open(path, encoding="utf-8") as f:
        return rel, json.load(f)


plans, models = {}, {}


def load_plan(rel, data):
    """(voiceover samples or None, words, reference tokens, language) for a plan; None if it has no speech."""
    vo_rel = a.vo or data.get("vo") or next((s["source"] for s in data.get("shots", [])      # as edit.py: an avatar
                                              if s.get("type") == "avatar" and s.get("source")), None)  # video is the VO
    if data.get("shots") and not vo_rel and all(s.get("type") == "text" for s in data["shots"]):
        return None                                       # text-only ad (option 5): nothing is spoken
    vo = None
    if vo_rel:
        vp = os.path.join(a.project, vo_rel)
        if not os.path.exists(vp):
            sys.exit(f"The voiceover {vp} (from {'--vo' if a.vo else rel}) doesn't exist.")
        vo = load_audio(vp, 8000)
        if len(vo) < 8000:
            sys.exit(f"The voiceover {vp} has less than a second of sound.")
    wp = os.path.join(a.project, a.words or data.get("words", "words.json"))
    if not os.path.exists(wp):
        sys.exit(f"No word timings at {wp}. Run transcribe.py first.")
    with open(wp, encoding="utf-8") as f:
        ref = json.load(f)
    # What Whisper heard where transcribe.py took the script's spelling: the final is heard the same way.
    # Words with no letters (a dash, an emoji) can never be heard, so they don't count.
    tok = [(norm(x), i) for i, w in enumerate(ref) for x in str(w.get("heard", w["w"])).split() if norm(x)]
    return vo, ref, tok, (a.language or data.get("language") or "en").lower()


def as_written(ref, tok, i1, i2, got_part):
    """True if the final has these words as the script spells them (a hand-fixed "w"), not as Whisper heard
    them in the voiceover: the final, with music under it, is sometimes heard better than the voiceover alone."""
    entries = sorted({tok[k][1] for k in range(i1, i2)})
    written, heard = "".join(norm(ref[e]["w"]) for e in entries), "".join(got_part)
    return bool(written) and difflib.SequenceMatcher(None, written, heard).ratio() >= 0.85


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
        for lag in range(-1600, 1601, 40):
            j = i + lag
            if j < 0 or j + n > len(fin):
                continue
            seg = fin[j:j + n]
            c = float(np.dot(w, seg) / (np.linalg.norm(w) * np.linalg.norm(seg) + 1e-9))
            if c > best[0]:
                best = (c, lag / 8000)
        # music under the voice lowers the match a little; a dropped or shifted chunk drops it a lot
        if best[0] < (0.7 if music else 0.85) or abs(best[1]) > 0.02:
            errs.append(f"{t:.1f}s (match {best[0]:.2f}, offset {best[1] * 1000:+.0f}ms)")
    return errs


bad = 0
for path in finals:
    rel, data = plan_for(os.path.basename(path))
    if rel not in plans:
        plans[rel] = load_plan(rel, data)
    if plans[rel] is None:
        print(f"PASS  {os.path.basename(path)}: no speech to check (text-only ad, {rel})")
        continue
    vo, ref, tok, lang = plans[rel]
    name = a.model or ("small.en" if lang == "en" else "small")
    if name not in models:
        models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    segs, _ = models[name].transcribe(load_audio(path), language=lang, word_timestamps=True)
    got = [norm(w.word) for s in segs for w in s.words if norm(w.word)]
    want = [t for t, _ in tok]
    sm = difflib.SequenceMatcher(None, want, got, autojunk=False)
    matched, missing = 0, []
    for op in sm.get_opcodes():
        kind, i1, i2, j1, j2 = op
        # the same words heard a little differently ("quizre" in the voiceover, "quizra" in the final) are there
        if kind == "equal" or kind == "replace" and (i2 - i1 == j2 - j1 and all(
                difflib.SequenceMatcher(None, want[i1 + k], got[j1 + k]).ratio() >= 0.75 for k in range(i2 - i1))
                or as_written(ref, tok, i1, i2, got[j1:j2])):
            matched += i2 - i1
        elif kind in ("delete", "replace") and i2 - i1 > 2:
            missing.append(op)
    ratio = matched / max(len(tok), 1)
    werr = waveform_check(vo, path, data.get("music")) if vo is not None else []
    # With every moment of the voiceover's waveform in place, no word can be missing: words that differ are
    # Whisper hearing the mixed sound differently, so they're noted. Without a voiceover file they decide.
    vouched = vo is not None and not werr
    ok = not werr and (vouched or ratio >= 0.93 and not missing)
    bad += not ok
    wave = "no voiceover file" if vo is None else ("identical to the voiceover" if not werr else "MISMATCH")
    print(f"{'PASS' if ok else 'FAIL'}  {os.path.basename(path)}: {matched}/{len(tok)} words in place, waveform {wave}"
          + (f" ({rel})" if rel != "shots.json" else ""))
    for e in werr[:8]:
        print(f"      voiceover missing or shifted at {e}")
    for op in missing:
        i, j = tok[op[1]][1], tok[op[2] - 1][1] + 1
        what = "heard differently (the waveform shows it's there)" if vouched else "missing or changed"
        print(f"      {what} at {ref[i]['s']:.1f}s: \"{' '.join(w['w'] for w in ref[i:j])}\"")
sys.exit(1 if bad else 0)
