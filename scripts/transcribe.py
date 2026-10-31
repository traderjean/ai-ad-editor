"""Word timings for a voiceover (or a talking-avatar clip) and a first draft of the shots.

    transcribe.py <vo file> <project> [--script inputs/script.txt [--trust-script]] [--max-shot 8]
                  [--language fr] [--words-out words.json] [--no-draft]

Writes <project>/words.json and <project>/shots_draft.json (an existing words file is kept as
<name>.bak). With --script, words Whisper misheard (names, brand words) are replaced by the script's
spelling where the two line up one for one; anything it can't line up is printed so you can fix it
by hand. What Whisper heard is kept as "heard" on those words, for verify_vo.py.
--trust-script (for a voiceover generated from the script): what can't be lined up takes the script's
words too, spread over the time Whisper heard something there, so nothing is left to fix by hand.
If less than half of the script is heard (the wrong language, voiceover or script), nothing is written.
Shots break at sentence ends or pauses and are never longer than --max-shot seconds
(default: the video slot's max_seconds in providers.json).
For a voiceover that isn't in English pass --language (e.g. fr): the multilingual Whisper model
is used instead of the English-only one.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_audio, load_settings

ap = argparse.ArgumentParser()
ap.add_argument("vo")
ap.add_argument("project")
ap.add_argument("--script", help="the approved script, to fix misheard words")
ap.add_argument("--trust-script", action="store_true",
                help="the voiceover was generated from the script: take the script's words everywhere")
ap.add_argument("--max-shot", type=float)
ap.add_argument("--language", type=str.lower, help="the voiceover's language code, e.g. fr (default: en)")
ap.add_argument("--model", help="Whisper model (default: small.en for English, else small)")
ap.add_argument("--words-out", default="words.json")
ap.add_argument("--no-draft", action="store_true", help="only write the word timings")
a = ap.parse_args()
if a.trust_script and not a.script:
    ap.error("--trust-script needs --script (the script the voiceover was generated from)")
max_shot = a.max_shot or float(load_settings()["video"].get("max_seconds", 8))

from faster_whisper import WhisperModel

os.makedirs(a.project, exist_ok=True)
model = WhisperModel(a.model or ("small.en" if a.language in (None, "en") else "small"), device="cpu",
                     compute_type="int8")
segments, _ = model.transcribe(load_audio(a.vo), language=a.language, word_timestamps=True, vad_filter=False)
words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
         for seg in segments for w in seg.words if w.word.strip()]


def norm(t):
    """Letters and digits only, accents dropped ("Été" -> "ete")."""
    return "".join(c for c in unicodedata.normalize("NFKD", t.casefold()) if c.isalnum())


def spread(texts, t0, t1, heard):
    """The script's words over t0..t1, evenly. What Whisper heard there goes on the first, for verify_vo.py."""
    n = len(texts)
    new = [{"w": x, "s": round(t0 + (t1 - t0) * k / n, 2), "e": round(t0 + (t1 - t0) * (k + 1) / n, 2), "heard": ""}
           for k, x in enumerate(texts)]
    new[0]["heard"] = heard
    return new


# ---- fix misheard words against the script ----
if a.script:
    with open(a.script, encoding="utf-8-sig") as f:
        toks = re.sub(r"\[[^\]]*\]", " ", f.read()).split()   # drop [audio tags]
    # French typography puts a space before ? ! : ; and inside « »: keep each mark on its word, so sentence ends
    # still end draft shots and caption chunks ("encore ?" -> "encore?").
    script_words = []
    for t in toks:
        if script_words and not norm(t) and all(c in "?!:;»….,)]”’%" for c in t):
            script_words[-1] += t
        elif script_words and all(c in "«¿¡“‘([" for c in script_words[-1]):
            script_words[-1] += t
        else:
            script_words.append(t)
    sm = difflib.SequenceMatcher(None, [norm(w["w"]) for w in words], [norm(x) for x in script_words], autojunk=False)
    ops = sm.get_opcodes()
    # Too little of the script heard: the wrong language (an English-only model on French), voiceover or script.
    lined_up = sum(j2 - j1 for op, i1, i2, j1, j2 in ops if op == "equal" or op == "replace" and (
        i2 - i1 == j2 - j1 or "".join(norm(w["w"]) for w in words[i1:i2]) == "".join(norm(x) for x in script_words[j1:j2])))
    total_script = sum(1 for x in script_words if norm(x))
    if total_script and lined_up < 0.5 * total_script:
        if not words:
            sys.exit(f"No speech was heard in {a.vo}: check that it's the voiceover (with the voice in it). "
                     "Nothing was written.")
        lang = "English" if a.language in (None, "en") else f'"{a.language}"'
        sys.exit(f"Only {100 * lined_up // total_script}% of the script was heard in {a.vo}. Is the voiceover in "
                 f"{lang}? Pass --language <code> for another language (e.g. --language fr), check that this is the "
                 f"right voiceover and script ({a.script}), or run without --script to time the words as heard. "
                 "Nothing was written.")
    fixed, unsure, tail = 0, [], []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":       # same word: still take the script's spelling (brand capitals, punctuation)
            for k in range(i2 - i1):
                words[i1 + k]["w"] = script_words[j1 + k]
        elif op == "replace" and "".join(norm(w["w"]) for w in words[i1:i2]) == "".join(norm(x) for x in script_words[j1:j2]):
            # Same letters, split differently ("sister -in -law", "drug store"): spread the script's words over
            # the heard time span. Marked so the second pass below can rebuild the list.
            span = words[i1:i2]
            new = spread(script_words[j1:j2], span[0]["s"], span[-1]["e"], " ".join(w["w"] for w in span))
            for k, w in enumerate(span):
                w["_replace"] = new if k == 0 else []
            fixed += j2 - j1
        elif op == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                words[i1 + k]["heard"] = words[i1 + k]["w"]
                words[i1 + k]["w"] = script_words[j1 + k]
                fixed += 1
        elif op == "insert" and not "".join(norm(x) for x in script_words[j1:j2]):
            pass                        # a dash or "&" in the script with nothing heard for it
        elif op == "delete" and not "".join(norm(w["w"]) for w in words[i1:i2]):
            for w in words[i1:i2]:      # a "%" or "-" heard on its own, already on the script's word
                w["_replace"] = []
        elif a.trust_script and op != "equal":
            # Generated from the script, so the script is what it says: its words take the time Whisper heard
            # something else there, or the gap between the words around them.
            want = " ".join(script_words[j1:j2])
            heard = " ".join(w["w"] for w in words[i1:i2])
            if op == "delete":
                for w in words[i1:i2]:
                    w["_replace"] = []
                print(f'  dropped words the script doesn\'t have at {words[i1]["s"]:.1f}s: "{heard}"')
                continue
            if op == "replace":
                new = spread(script_words[j1:j2], words[i1]["s"], words[i2 - 1]["e"], heard)
                for k, w in enumerate(words[i1:i2]):
                    w["_replace"] = new if k == 0 else []
            else:                       # insert: nothing heard for these words
                n = j2 - j1
                t0 = words[i1 - 1]["e"] if i1 else 0.0
                t1 = words[i1]["s"] if i1 < len(words) else t0 + 0.3 * n
                if t1 - t0 < 0.08 * n and i1:     # no room: take it from the end of the word before
                    prev = words[i1 - 1]
                    t0 = max(round((prev["s"] + prev["e"]) / 2, 2), round(t1 - 0.08 * n, 2))
                    prev["e"] = t0
                new = spread(script_words[j1:j2], t0, max(t1, t0), "")
                if i1 < len(words):
                    words[i1]["_before"] = words[i1].get("_before", []) + new
                else:
                    tail += new
            fixed += j2 - j1
            print(f'  took the script\'s words at {new[0]["s"]:.1f}s: "{want}" '
                  + (f'(heard "{heard}")' if heard else "(heard nothing there)"))
        elif op != "equal":
            for w in words[i1:i2]:
                w["heard"] = w["w"]     # kept when you fix the spelling by hand
            heard = " ".join(w["w"] for w in words[i1:i2])
            want = " ".join(script_words[j1:j2])
            where = words[min(i1, len(words) - 1)]["s"] if words else 0
            unsure.append(f'{where:.1f}s  ' + (f'heard "{heard}"' if heard else "heard nothing") + "  " +
                          (f'script says "{want}"' if want else "the script doesn't have it"))
    rebuilt = []
    for w in words:
        rebuilt += w.pop("_before", [])
        if "_replace" in w:
            rebuilt += w["_replace"]
        else:
            rebuilt.append(w)
    words = rebuilt + tail
    print(f"Fixed {fixed} word(s) to match the script.")
    for u in unsure:
        print("  CHECK BY HAND:", u)
    left = [w for w in words if w.get("heard") == w["w"]]
    if left or unsure:
        print(f"{len(left)} word(s) are still as Whisper heard them, not as the script says, and the captions show "
              f"them that way. Fix each CHECK BY HAND line in {a.words_out}: change \"w\" and keep \"heard\", add a "
              "missing word with \"heard\": \"\", delete a word the voiceover doesn't say, and delete \"heard\" from a "
              "word it really says that way. Or, if the voiceover was generated from this script, run this again "
              "with --trust-script.")
    else:
        print("Every word follows the script.")

out = os.path.join(a.project, a.words_out)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)     # e.g. audio/<id>_words.json
kept = os.path.exists(out)
if kept:    # hand fixes in the old file aren't lost (e.g. a hook's voiceover transcribed without --words-out)
    shutil.copy(out, out + ".bak")
with open(out, "w", encoding="utf-8") as f:
    json.dump(words, f, indent=1)
total = words[-1]["e"] if words else 0
print(f"{len(words)} words, {total:.1f}s -> {a.words_out}" + (f" (the old one is now {a.words_out}.bak)" if kept else ""))
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
# max_shot (pauses get added to it), so any shot that ends up too long is split, again and again
# until every piece fits: in a silence of 1s or more before or after its words when they fit in one
# shot (the silence becomes a shot of its own), else at the word nearest the middle.
for i, s in enumerate(shots):
    s["start"] = 0.0 if i == 0 else s["start"]
    if i + 1 < len(shots):
        s["end"] = shots[i + 1]["start"]
split, todo = [], shots[::-1]
while todo:
    s = todo.pop()
    if s["end"] - s["start"] <= max_shot + 0.01:
        split.append(s)
        continue
    inside = [w for w in words if s["start"] <= w["s"] < s["end"]]
    later = [w for w in inside if w["s"] > s["start"]]
    talk = (inside[0]["s"], inside[-1]["e"]) if inside else (s["start"], s["start"])
    if inside and talk[1] - s["start"] > max_shot and talk[1] - talk[0] <= max_shot and talk[0] - s["start"] >= 1:
        cut = talk[0]                   # a long silence before the words
    elif talk[1] - s["start"] <= max_shot and (s["end"] - talk[1] >= 1 or not later):
        # in the silence after them, halfway between the earliest and latest cut that keep both pieces short
        lo, hi = max(talk[1], s["end"] - max_shot), s["start"] + max_shot
        cut = round((lo + hi) / 2 if lo <= hi else hi, 2)
    elif later:
        mid = (s["start"] + s["end"]) / 2
        cut = min(later, key=lambda w: abs(w["s"] - mid))["s"]
    else:
        cut = s["start"] + max_shot     # one very long word
    # every cut is strictly inside the shot, so this ends
    todo.append({"text": " ".join(w["w"] for w in inside if w["s"] >= cut), "start": cut, "end": s["end"]})
    todo.append({"text": " ".join(w["w"] for w in inside if w["s"] < cut), "start": s["start"], "end": cut})
shots = split
for i, s in enumerate(shots):
    s["id"] = f"s{i + 1:02d}"
with open(os.path.join(a.project, "shots_draft.json"), "w", encoding="utf-8") as f:
    json.dump(shots, f, indent=2)
print(f"{len(shots)} draft shots (max {max_shot:g}s)")
for s in shots:
    print(f'{s["id"]}  {s["start"]:6.2f}-{s["end"]:6.2f} ({s["end"] - s["start"]:.1f}s)  {s["text"]}')
