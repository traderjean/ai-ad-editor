"""Check finished ads against the voiceover. Run on EVERY final before it goes to anyone.

    verify_vo.py <project> final/ad1.mp4 [final/ad2.mp4 ...] [--shots shots.json]

Two checks per file:
  1. Waveform: every 2s stretch of the voiceover is in the final at the same moment (within 20ms).
     This catches dropped chunks, gaps and drift that a listen-through misses.
  2. Words: the final is transcribed and every word of words.json must be there, in order.
Prints PASS or FAIL for each file; exits 1 if any file fails.
For ads with no separate voiceover file (text-only, or the video tool's own voices) only the
word check runs, against the words file given in the shots file.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ffmpeg

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("finals", nargs="+")
ap.add_argument("--shots", default="shots.json")
ap.add_argument("--words", help="default: the shots file's words, else words.json")
ap.add_argument("--vo", help="voiceover to compare against (default: the shots file's vo)")
a = ap.parse_args()

import numpy as np
from faster_whisper import WhisperModel

data = {}
sp = os.path.join(a.project, a.shots)
if os.path.exists(sp):
    with open(sp) as f:
        data = json.load(f)
vo_rel = a.vo or data.get("vo")
words_rel = a.words or data.get("words", "words.json")


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def pcm(path):
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(float)


vo = None
if vo_rel and os.path.splitext(vo_rel)[1].lower() in (".mp3", ".wav", ".m4a", ".aac", ".mp4", ".mov"):
    vo = pcm(os.path.join(a.project, vo_rel))


def waveform_check(path):
    if vo is None:
        return []
    fin, errs = pcm(path), []
    for t in np.arange(0, len(vo) / 8000 - 1, 2.0):
        i = int(t * 8000)
        w = vo[i:i + 4000]
        if np.abs(w).max() < 300:
            continue          # silence: nothing to match
        best = (-1, 0)
        for lag in range(-1600, 1601, 40):
            j = i + lag
            if j < 0 or j + 4000 > len(fin):
                continue
            seg = fin[j:j + 4000]
            c = float(np.dot(w, seg) / (np.linalg.norm(w) * np.linalg.norm(seg) + 1e-9))
            if c > best[0]:
                best = (c, lag / 8000)
        # music under the voice lowers the match a little; a dropped or shifted chunk drops it a lot
        if best[0] < (0.7 if data.get("music") else 0.85) or abs(best[1]) > 0.02:
            errs.append(f"{t:.0f}s (match {best[0]:.2f}, offset {best[1] * 1000:+.0f}ms)")
    return errs


wp = os.path.join(a.project, words_rel)
if not os.path.exists(wp):
    sys.exit(f"No word timings at {wp}. Run transcribe.py first.")
with open(wp) as f:
    ref = json.load(f)
ref_n = [norm(w["w"]) for w in ref]
model = WhisperModel("small.en", device="cpu", compute_type="int8")
bad = 0
for f in a.finals:
    path = f if os.path.isabs(f) else os.path.join(a.project, f)
    segs, _ = model.transcribe(path, word_timestamps=True)
    got = [norm(w.word) for s in segs for w in s.words if norm(w.word)]
    sm = difflib.SequenceMatcher(None, ref_n, got, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    ratio = matched / max(len(ref_n), 1)
    missing = [op for op in sm.get_opcodes() if op[0] in ("delete", "replace") and op[2] - op[1] > 2]
    werr = waveform_check(path)
    ok = not werr and ratio >= 0.93 and not missing
    bad += not ok
    wave = "no voiceover file" if vo is None else ("identical to the voiceover" if not werr else "MISMATCH")
    print(f"{'PASS' if ok else 'FAIL'}  {os.path.basename(f)}: {matched}/{len(ref_n)} words in place, waveform {wave}")
    for e in werr[:8]:
        print(f"      voiceover missing or shifted at {e}")
    for op in missing:
        print(f"      missing or changed at {ref[op[1]]['s']:.1f}s: \"{' '.join(w['w'] for w in ref[op[1]:op[2]])}\"")
sys.exit(1 if bad else 0)
