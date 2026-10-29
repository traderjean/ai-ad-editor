"""Word timings for a voiceover (or a talking-avatar clip) and a first draft of the shots.

    transcribe.py <vo file> <project> [--script inputs/script.txt] [--max-shot 8]

Writes <project>/words.json and <project>/shots_draft.json. With --script, words Whisper misheard
(names, brand words) are replaced by the script's spelling where the two line up one for one;
anything it can't line up is printed so you can fix it by hand.
Shots break at sentence ends or pauses and are never longer than --max-shot seconds
(default: the video slot's max_seconds in providers.json).
"""
import argparse
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_settings

ap = argparse.ArgumentParser()
ap.add_argument("vo")
ap.add_argument("project")
ap.add_argument("--script", help="the approved script, to fix misheard words")
ap.add_argument("--max-shot", type=float)
ap.add_argument("--model", default="small.en")
ap.add_argument("--words-out", default="words.json")
ap.add_argument("--no-draft", action="store_true", help="only write the word timings")
a = ap.parse_args()
max_shot = a.max_shot or float(load_settings()["video"].get("max_seconds", 8))

from faster_whisper import WhisperModel

os.makedirs(a.project, exist_ok=True)
model = WhisperModel(a.model, device="cpu", compute_type="int8")
segments, _ = model.transcribe(a.vo, word_timestamps=True, vad_filter=False)
words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
         for seg in segments for w in seg.words if w.word.strip()]


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


# ---- fix misheard words against the script ----
if a.script:
    script_words = re.sub(r"\[[^\]]*\]", " ", open(a.script).read()).split()   # drop [audio tags]
    sm = difflib.SequenceMatcher(None, [norm(w["w"]) for w in words], [norm(x) for x in script_words], autojunk=False)
    fixed, unsure = 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":       # same word: still take the script's spelling (brand capitals, punctuation)
            for k in range(i2 - i1):
                words[i1 + k]["w"] = script_words[j1 + k]
        elif op == "replace" and "".join(norm(w["w"]) for w in words[i1:i2]) == "".join(norm(x) for x in script_words[j1:j2]):
            # Same letters, split differently ("sister -in -law", "drug store"): spread the script's words over
            # the heard time span. Marked so the second pass below can rebuild the list.
            span = words[i1:i2]
            n = j2 - j1
            t0, t1 = span[0]["s"], span[-1]["e"]
            new = [{"w": script_words[j1 + k], "s": round(t0 + (t1 - t0) * k / n, 2),
                    "e": round(t0 + (t1 - t0) * (k + 1) / n, 2)} for k in range(n)]
            for k, w in enumerate(span):
                w["_replace"] = new if k == 0 else []
            fixed += n
        elif op == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                words[i1 + k]["w"] = script_words[j1 + k]
                fixed += 1
        elif op != "equal":
            heard = " ".join(w["w"] for w in words[i1:i2])
            want = " ".join(script_words[j1:j2])
            where = words[min(i1, len(words) - 1)]["s"] if words else 0
            unsure.append(f'{where:.1f}s  heard "{heard}"  script says "{want}"')
    rebuilt = []
    for w in words:
        if "_replace" in w:
            rebuilt += w["_replace"]
        else:
            rebuilt.append(w)
    words = rebuilt
    print(f"Fixed {fixed} word(s) to match the script.")
    for u in unsure:
        print("  CHECK BY HAND:", u)

with open(os.path.join(a.project, a.words_out), "w") as f:
    json.dump(words, f, indent=1)
total = words[-1]["e"] if words else 0
print(f"{len(words)} words, {total:.1f}s -> {a.words_out}")
if a.no_draft:
    sys.exit(0)

# ---- draft shots: add words until the next would pass max_shot, then cut at the best boundary ----
shots, cur = [], []


def flush():
    if cur:
        shots.append({"text": " ".join(x["w"] for x in cur), "start": cur[0]["s"], "end": cur[-1]["e"]})


for w in words:
    if cur and w["e"] - cur[0]["s"] > max_shot:
        cut = len(cur)
        for j in range(len(cur) - 1, 0, -1):     # back up to the last sentence/comma/pause
            if cur[j - 1]["w"][-1] in ".?!,;:" or cur[j]["s"] - cur[j - 1]["e"] > 0.25:
                cut = j
                break
        rest = cur[cut:]
        cur = cur[:cut]
        flush()
        cur = rest
    cur.append(w)
    if w["w"][-1] in ".?!" and w["e"] - cur[0]["s"] > 2.5:
        flush()
        cur = []
flush()

# Shots touch end to end, so there is never a black gap. Closing the gaps can push a shot past
# max_shot (pauses get added to it), so any shot that ends up too long is split in two at a word.
for i, s in enumerate(shots):
    s["start"] = 0.0 if i == 0 else s["start"]
    if i + 1 < len(shots):
        s["end"] = shots[i + 1]["start"]
split = []
for s in shots:
    if s["end"] - s["start"] <= max_shot:
        split.append(s)
        continue
    inside = [w for w in words if s["start"] <= w["s"] < s["end"]]
    mid = (s["start"] + s["end"]) / 2
    cut = min(inside[1:], key=lambda w: abs(w["s"] - mid)) if len(inside) > 1 else None
    if not cut:
        split.append(s)
        continue
    k = inside.index(cut)
    split.append({"text": " ".join(w["w"] for w in inside[:k]), "start": s["start"], "end": cut["s"]})
    split.append({"text": " ".join(w["w"] for w in inside[k:]), "start": cut["s"], "end": s["end"]})
shots = split
for i, s in enumerate(shots):
    s["id"] = f"s{i + 1:02d}"
with open(os.path.join(a.project, "shots_draft.json"), "w") as f:
    json.dump(shots, f, indent=2)
print(f"{len(shots)} draft shots (max {max_shot:g}s)")
for s in shots:
    print(f'{s["id"]}  {s["start"]:6.2f}-{s["end"]:6.2f} ({s["end"] - s["start"]:.1f}s)  {s["text"]}')
