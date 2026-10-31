"""One entry point for every generation. Routes each job to the tool set for its slot in providers.json.

    generate.py image  --prompt "..." --out frames/s01.png [--ref sheet.png] [--n 3] [--quality draft|standard|best]
    generate.py images jobs.json [--only s03 s07] [--redo]  # several different images, one cost, one approval
    generate.py video  --prompt "..." --out clips/s01.mp4 [--frame frames/s01.png] [--audio] [--seconds 6]
    generate.py clips  <project> [--shots shots.json] [--only s03 s07] [--redo] [--fit]
    generate.py voice  --text-file script.txt --out audio/vo.mp3 --voice <voice id> [--quality draft|standard|best]
    generate.py voices                                    # list voices to pick from (free)
    generate.py lipsync --video clips/s04.mp4 --audio audio/s04.mp3 --out clips/s04_talk.mp4
    generate.py avatar  --image frames/host.png --audio audio/vo.mp3 --out clips/host.mp4 [--prompt "..."]
    generate.py music   --prompt "..." --out inputs/music.mp3 [--seconds 60] [--quality draft|standard|best]
    generate.py prices [--provider kie]                   # price per image, clip, 1,000 characters... (free)
    generate.py spend [<project>]                         # what each ad has cost so far, per slot (free)

Paid jobs print the estimate and stop; add --yes to run them. --provider <name> forces an API adapter.
Everything a run needs (key, prompts, frames, refs, files) is checked first: nothing runs until all of it is there.
`clips` and `images` skip files that already exist (--only remakes the named ones, --redo all of them); a remake
keeps the old take as <name>_prev. A paid job an earlier run started but didn't collect is finished, not paid twice.
Clips are --seconds long (default: the video slot's max_seconds, 8). `clips --fit` asks for each shot's own length
plus a little spare instead, which costs less on providers that bill per second (Replicate, Higgsfield);
Kie's Veo charges the same for any length (the edit trims each clip). `clips --shots shots_draft.json` prices a draft.
With a budget for the ad (check_setup.py --budget, inside the project) a run that would pass it is blocked.

Slot modes (providers.json):
  api     run it here with the adapter
  mcp     exit 3: Claude calls the MCP tool itself and saves the file to --out
  manual  exit 4: writes manual/<name>.md with everything the user needs to run it by hand
  none    exit 2: no tool chosen yet, run check_setup.py
"""
import argparse
import concurrent.futures as cf
import inspect
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers
from common import (QUALITIES, SLOTS, SPEND_LOG, check_spend, duration, find_project, load_budget, load_json,
                    load_settings, log_spend, mmss, project_name, spend_rows, spent, voiceover_file)

CLIP_TYPES = ("clip", "veo", "talking")      # shot types that need a generated clip ("veo" = old name)
FIT_MARGIN = 1.0                             # --fit: up to a spare second per clip for trims and small re-timings
FIT_PAD = 0.25                               # ... but for an adapter that rounds lengths up itself, only this much,
                                             # so a 3.1s shot stays a 4s clip instead of stepping up to 6s
# Error texts (providers/) that mean the job may exist and be paid for even though it failed here.
MAYBE_PAID = ("Made, but the download failed", "may have started", "Lost track", "may still finish")
# Error texts that can mean a safety filter turned the prompt down (Kie reports most of those as "task failed").
REFUSED = ("task failed", "failed (not charged)", "unsafe", "safety", "sensitive", "nsfw", "flagged", "moderation",
           "policy", "generate audio")


def route(slot, forced=None):
    """Returns ("api", adapter, cfg) or exits with the right code for mcp / manual / none."""
    cfg = load_settings().get(slot, {})
    if forced:
        p = providers.get(forced)
        if slot not in p.slots:
            sys.exit(f"{p.label} can't do {slot}. It does: {', '.join(p.slots)}")
        if forced != cfg.get("provider"):    # the slot's pinned model and voice belong to its own provider
            cfg = {k: v for k, v in cfg.items() if k not in ("model", "voice_id", "tool")}
        return "api", p, cfg
    mode = cfg.get("mode", "none")
    if mode == "api":
        return "api", providers.get(cfg.get("provider", "")), cfg
    if mode in ("mcp", "manual"):
        return mode, None, cfg
    print(f"No tool is set for {slot}. Run: python3 scripts/check_setup.py")
    sys.exit(2)


def handoff(mode, slot, cfg, out, prompt=None, refs=(), settings=None, quality=None, model=None):
    """MCP or manual: describe the job instead of running it. `out` is one path, or a list for several takes."""
    outs = out if isinstance(out, list) else [out]
    settings = {**(settings or {}), **({"takes": len(outs)} if len(outs) > 1 else {}),
                **({"quality": quality} if quality else {}), **({"model": model} if model else {})}
    where = outs[0] if len(outs) == 1 else ", ".join(outs)
    if mode == "mcp":
        print(f"MCP: call the tool '{cfg.get('tool', '?')}' for this {slot} job, then save the "
              f"{'result' if len(outs) == 1 else 'takes'} to {where}")
        print(json.dumps({"prompt": prompt, "refs": list(refs), **settings}, indent=2))
        sys.exit(3)
    folder = os.path.join(find_project(outs[0]), "manual")
    os.makedirs(folder, exist_ok=True)
    note = os.path.join(folder, os.path.splitext(os.path.basename(outs[0]))[0] + f"_{slot}.md")
    lines = [f"# {slot.title()} job: {', '.join(os.path.basename(o) for o in outs)}", "",
             f"Run this in your {slot} tool ({cfg.get('tool') or 'any tool you like'}).", ""]
    for k, v in settings.items():
        lines.append(f"- **{k}:** {v}")
    if refs:
        lines += ["", "**Attach these files, in this order:**"] + [f"{i}. `{r}`" for i, r in enumerate(refs, 1)]
    if prompt:
        lines += ["", "**Prompt (copy all of it):**", "", "```", prompt, "```"]
    if len(outs) == 1:
        lines += ["", f"**Save the result as:** `{os.path.abspath(outs[0])}`", ""]
    else:
        lines += ["", "**Save one take as each of these:**"] + [f"- `{os.path.abspath(o)}`" for o in outs] + [""]
    with open(note, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"MANUAL: instructions written to {note}")
    print(f"Waiting for {'the file at ' if len(outs) == 1 else 'the files '}{where}")
    sys.exit(4)


def length_for_tool(seconds):
    """MCP tools take whole seconds: round up, never down (a clip shorter than the shot freezes in the edit)."""
    return f"{math.ceil(seconds - 1e-6)}s"


# ---------- checks before anything is paid ----------

def pending(p, out):
    """The paid job an earlier run started for `out` and didn't collect (Provider.pending), else None.
    Stops when another provider left one there: making a new job would drop the paid one."""
    try:
        with open(out + ".job.json", encoding="utf-8") as f:
            other = json.load(f).get("provider")
    except (OSError, ValueError, AttributeError):
        other = None
    if p is not None and other and other != p.name:
        sys.exit(f"{os.path.basename(out)} has an unfinished {other} job from an earlier run (it's paid for): "
                 f"collect it with --provider {other}, or delete {out}.job.json to drop it, then run this again.")
    return p.pending(out) if p is not None and hasattr(p, "pending") else None


def finishing(label, job):
    return f"{label} (finishing job {job.get('id', '?')})"


def key_problem(p):
    if not p.has_key():
        return (f"{p.env_key} is not set: get a {p.label.split(' (')[0]} key at {p.signup}, add it to your shell "
                f"profile, open a new terminal, then run this again")


def quality_problem(p, slot, quality, model, who):
    if quality not in QUALITIES:
        return f'{who}: quality "{quality}" isn\'t one of {", ".join(QUALITIES)}'
    if p is not None and p.default_models.get(slot) and not p.model_for(slot, quality, model):
        return f"{who}: {p.label.split(' (')[0]} has no {quality} {slot} model: pick another quality or pass --model"


def file_problem(path, shown, who):
    if path and not os.path.isfile(path):
        return f"{who} {shown} doesn't exist"


def stop_on(problems):
    """Everything wrong with a run, found before anything is made, in one list."""
    problems = [x for x in problems if x]
    if problems:
        print("Fix these first (nothing was made or charged):")
        for x in problems:
            print(f"  - {x}")
        sys.exit(1)


def confirm(items, yes, remakes=(), project=None, problems=()):
    """items = list of (label, usd or None). remakes = the price of remaking each frame that may come out
    letterboxed (see make_image). problems = what must be fixed first: listed under the estimate, and with
    --yes nothing runs. Prints the estimate; stops unless --yes. Returns False when those remakes could
    take the run over the spend limit or the ad's budget, so they're skipped."""
    problems = [x for x in problems if x]
    known = [c for _, c in items if c is not None]
    for label, c in items:
        print(f"  {label:40} {'$%.3f' % c if c is not None else 'cost unknown'}")
    total = sum(known)
    if known:
        print(f"{len(items)} job(s), about ${total:.2f}" + (" (some costs unknown)" if len(known) < len(items) else ""))
    else:
        print(f"{len(items)} job(s), cost unknown: there's no price table for this model, so the per-run limit "
              f"and the ad's budget can't count it (the real cost shows after the run when the provider reports it)")
    if yes:
        stop_on(problems)
    check_spend(total if known else None, project)
    ok = True
    if remakes:
        extra = None if None in remakes else sum(remakes)
        limit = load_settings().get("spend_limit_per_run")
        budget = load_budget(project)
        over_limit = bool(limit and extra and total + extra > limit)
        over_budget = bool(budget and extra and spent(project)[0] + total + extra > budget)
        ok = not (over_limit or over_budget)
        if ok:
            each = "cost unknown" if extra is None else f"${remakes[0]:.3f} each"
            print(f"A frame that comes out letterboxed is remade once on the best model ({each}, not in the total).")
        else:
            cap = f"${limit:.2f} per-run limit" if over_limit else f"${budget:.2f} budget for this ad"
            print(f"Letterboxed frames won't be remade this run (up to ${extra:.2f} more would pass your {cap}): "
                  f"they get a CHECK line instead.")
    if problems:
        print("Fix these first (nothing was made or charged):")
        for x in problems:
            print(f"  - {x}")
        print("Estimate only. Fix them, then re-run with --yes.")
        sys.exit(0)
    if not yes:
        print("Estimate only. Re-run with --yes to generate.")
        sys.exit(0)
    return ok


def keep_old(out):
    # A copy, not a move: adapters write `out` only once the result is in hand, so a failed job leaves the
    # current file where it is (and an input that is also the output can still be read).
    if os.path.exists(out):
        base, ext = os.path.splitext(out)
        shutil.copy2(out, f"{base}_prev{ext}")


def show_spent(project):
    done, unknown = spent(project)
    budget = load_budget(project)
    print(f"Spent on this ad so far: ${done:.2f}" + (f" of your ${budget:.2f} budget" if budget else "")
          + (f" (plus {unknown} job(s) of unknown cost)" if unknown else ""))


# ---------- commands ----------

def looks_banded(path):
    """True if a tall image looks letterboxed: a matching pair of full-width edges near the top and bottom
    with blurred or empty space outside them. It can flag a real horizontal edge (a tabletop), so a hit
    only triggers one remake on the best model, which very rarely adds bands."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return False
    im = Image.open(path).convert("L")
    if im.height <= im.width:
        return False
    g = np.asarray(im.resize((270, 480)), dtype=float)
    h = g.shape[0]
    frac = (np.abs(g[1:] - g[:-1]) > 14).mean(axis=1)       # share of the width that changes at each row
    detail = np.abs(np.diff(g, axis=1)).mean(axis=1)
    best, pair = 0, None
    for t in range(int(h * .05), int(h * .42)):
        for b in range(h - 1 - t - int(h * .06), min(h - 1, h - 1 - t + int(h * .06))):
            s = min(frac[t], frac[b])
            if s > best:
                best, pair = s, (t, b)
    if not pair:
        return False
    t, b = pair
    outer = np.r_[detail[:t], detail[b:]].mean()
    return best > 0.4 and outer / (detail[t:b].mean() + 1e-9) < 0.6


def remake_prices(p, qualities, model):
    """The price of remaking a banded frame on the best model, once per job that can be remade (see make_image)."""
    return [p.estimate("image", "best") for q in qualities if q != "best" and not model]


def cmd_image(a):
    stop_on([file_problem(a.prompt_file, a.prompt_file, "--prompt-file")] + [file_problem(r, r, "--ref") for r in a.ref])
    prompt = open(a.prompt_file, encoding="utf-8").read().strip() if a.prompt_file else a.prompt
    mode, p, cfg = route("image", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    model = a.model or cfg.get("model")
    base, ext = os.path.splitext(a.out)
    outs = [a.out] if a.n == 1 else [f"{base}_{i + 1}{ext or '.png'}" for i in range(a.n)]
    if mode != "api":
        stop_on([None if prompt else "the prompt is empty"])
        handoff(mode, "image", cfg, outs, prompt, a.ref, {"aspect ratio": a.aspect}, quality, model)
    project = find_project(a.out)
    jobs = {o: pending(p, o) for o in outs}
    est = p.estimate("image", quality, model=model) if quality in QUALITIES else None
    remake = confirm([(finishing(os.path.basename(o), j), 0.0) if j else (os.path.basename(o), est)
                      for o, j in jobs.items()], a.yes, remake_prices(p, [quality] * len(outs), model), project,
                     [key_problem(p), quality_problem(p, "image", quality, model, "--quality"),
                      None if prompt or all(jobs.values()) else "the prompt is empty"])

    run_parallel(outs, lambda o: make_image(p, prompt, o, a.ref, a.aspect, quality, model, remake, project),
                 f"{p.name}-image", project=project, p=p)


def make_image(p, prompt, o, refs, aspect, quality, model, remake=True, project=None):
    os.makedirs(os.path.dirname(os.path.abspath(o)), exist_ok=True)
    keep_old(o)
    r = p.image(prompt, o, refs=refs, aspect=aspect, quality=quality, model=model)
    if remake and quality != "best" and not model and looks_banded(o):
        # Image models sometimes letterbox a tall frame. Remake once on the best model.
        base_, ext_ = os.path.splitext(o)
        os.replace(o, f"{base_}_banded{ext_}")
        try:
            r2 = p.image(prompt, o, refs=refs, aspect=aspect, quality="best")
        except Exception as e:
            os.replace(f"{base_}_banded{ext_}", o)     # the first take is paid for: keep it where the next steps look
            r.note += f" | CHECK: looks banded, and the remake on best failed ({e})"
            return r
        log_spend(f"{p.name}-image {os.path.basename(o)} (banded, remade)", r.cost, project)
        r = r2
        r.note += " (remade on best: first take had bands)"
    if looks_banded(o):
        r.note += " | CHECK: may still have bands, look at it"
    return r


def cmd_images(a):
    """Several different images (character options, a set of frames) priced and approved together."""
    jobs = load_json(a.jobs)
    if not isinstance(jobs, list):
        sys.exit(f'{a.jobs} should be a list of jobs: [{{"prompt": "...", "out": "frames/s01.png"}}, ...]')
    root = os.path.dirname(os.path.abspath(a.jobs))

    def at(path):
        return path if os.path.isabs(path) else os.path.join(root, path)
    problems = []
    for n, j in enumerate(jobs, 1):
        if not isinstance(j, dict) or not isinstance(j.get("out"), str) or not j["out"].strip():
            problems.append(f'job {n} in {a.jobs} has no "out" (the file to write)')
            continue
        j["name"] = j["out"]           # as written in the jobs file, for messages
        j["out"] = at(j["out"])
        refs = j.get("refs") or []
        j["refs"] = [at(r) for r in ([refs] if isinstance(refs, str) else refs)]
    jobs = [j for j in jobs if isinstance(j, dict) and j.get("name")]
    mode, p, cfg = route("image", a.provider)
    model = a.model or cfg.get("model")
    default_q = a.quality or cfg.get("quality", "standard")

    def named(j):
        stem = os.path.splitext(os.path.basename(j["out"]))[0]
        return {os.path.basename(j["out"]), stem, j["name"]} & set(a.only or ())
    if a.only:
        bad = [x for x in a.only if not any(x in (os.path.basename(j["out"]), os.path.splitext(os.path.basename(j["out"]))[0],
                                                  j["name"]) for j in jobs)]
        if bad:
            sys.exit(f"Not in {a.jobs}: {', '.join(bad)}. Name jobs by their file (s03.png) or its name (s03).")
    todo, have = [], 0
    for j in jobs:
        j["job"] = pending(p, j["out"])
        if j["job"]:                   # a paid job from an earlier run: collect it, never skip it
            todo.append(j)
        elif a.only:
            if named(j):
                todo.append(j)
        elif a.redo or not os.path.exists(j["out"]):
            todo.append(j)
        else:
            have += 1
    if have:
        print(f"{have} image(s) already exist and are skipped (--redo remakes them all, --only s03 s07 picks some).")
    if not todo:
        stop_on(problems)
        print("Nothing to make: every image already exists (use --only or --redo to make new takes).")
        return
    for j in todo:
        who = j["name"]
        if j["job"]:
            continue
        if j.get("prompt_file"):
            pf = at(j["prompt_file"])
            if os.path.isfile(pf):
                j["prompt"] = open(pf, encoding="utf-8").read().strip()
            else:
                problems.append(f"{who}: prompt_file {j['prompt_file']} doesn't exist")
                continue
        if not str(j.get("prompt") or "").strip():
            problems.append(f'{who}: no "prompt"')
        problems += [file_problem(r, os.path.relpath(r, root), f"{who}: ref") for r in j["refs"]]
        problems.append(quality_problem(p, "image", j.get("quality", default_q), model, who))
    if mode != "api":
        stop_on(problems)
        for j in todo:         # one instruction file per image, then hand over
            try:
                handoff(mode, "image", cfg, j["out"], j["prompt"], j["refs"], {"aspect ratio": j.get("aspect", "9:16")},
                        j.get("quality", default_q), model)
            except SystemExit:
                continue
        sys.exit(3 if mode == "mcp" else 4)
    project = find_project(a.jobs)

    def price(j):
        q = j.get("quality", default_q)
        if j["job"]:
            return finishing(os.path.basename(j["out"]), j["job"]), 0.0
        return os.path.basename(j["out"]), p.estimate("image", q, model=model) if q in QUALITIES else None
    remake = confirm([price(j) for j in todo], a.yes, remake_prices(p, [j.get("quality", default_q) for j in todo], model),
                     project, [key_problem(p)] + problems)
    run_parallel(todo, lambda j: make_image(p, j.get("prompt", ""), j["out"], j["refs"], j.get("aspect", "9:16"),
                                            j.get("quality", default_q), model, remake, project),
                 f"{p.name}-image", out=lambda j: j["out"], project=project, p=p)


def price_of(p, slot, quality, **kw):
    """p.estimate(), or None for a tier or pinned model the adapter can't price."""
    if quality not in QUALITIES:
        return None
    try:
        return p.estimate(slot, quality, **kw)
    except Exception:
        return None


def same_price_any_length(p, quality, model, audio=False):
    """True when the provider charges the same for a short clip as for a full one (Kie's Veo makes 8s clips)."""
    short, full = (price_of(p, "video", quality, seconds=x, model=model, audio=audio) for x in (2, 8))
    return short is not None and short == full


def cmd_video(a):
    stop_on([file_problem(a.prompt_file, a.prompt_file, "--prompt-file"), file_problem(a.frame, a.frame, "--frame")])
    prompt = open(a.prompt_file, encoding="utf-8").read().strip() if a.prompt_file else a.prompt
    mode, p, cfg = route("video", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    seconds = a.seconds or cfg.get("max_seconds", 8)
    model = a.model or cfg.get("model")
    if mode != "api":
        stop_on([None if prompt else "the prompt is empty"])
        handoff(mode, "video", cfg, a.out, prompt, [a.frame] if a.frame else [],
                {"aspect ratio": a.aspect, "length": length_for_tool(seconds),
                 "start frame": a.frame or "none", "sound": "on" if a.audio else "off (mute it)"},
                quality, model)
    project = find_project(a.out)
    job = pending(p, a.out)
    if a.seconds and same_price_any_length(p, quality, model, a.audio):
        print(f"{p.label.split(' (')[0]} charges the same for any clip length, so the clip may come back longer "
              f"than --seconds: the edit trims it.")
    est = p.estimate("video", quality, seconds=seconds, model=model, audio=a.audio) if quality in QUALITIES else None
    confirm([(finishing(os.path.basename(a.out), job), 0.0) if job else (os.path.basename(a.out), est)], a.yes,
            project=project, problems=[key_problem(p), quality_problem(p, "video", quality, model, "--quality"),
                                       None if prompt or job else "the prompt is empty"])

    def one(o):
        os.makedirs(os.path.dirname(os.path.abspath(o)), exist_ok=True)
        keep_old(o)
        return p.video(prompt, o, frame=a.frame, seconds=seconds, aspect=a.aspect, quality=quality, audio=a.audio,
                       model=model)
    run_parallel([a.out], one, f"{p.name}-video", project=project, p=p)


def cmd_clips(a):
    data = load_json(os.path.join(a.project, a.shots))
    draft = isinstance(data, list)
    if draft:                          # shots_draft.json is a bare list of shots: price it as it is
        data = {"shots": data}
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list) or not all(isinstance(s, dict) and s.get("id") for s in shots):
        sys.exit(f'{a.shots} should hold {{"shots": [{{"id": "s01", "start": 0, "end": 3.2, ...}}, ...]}} '
                 f'with an "id" on every shot.')
    if a.only:
        bad = [i for i in a.only if i not in {s["id"] for s in shots if s.get("type", "clip") in CLIP_TYPES}]
        if bad:
            sys.exit(f"Not a clip shot in {a.shots}: {', '.join(bad)}")
    mode, p, cfg = route("video", a.provider)
    clips_dir = os.path.join(a.project, "clips")

    def out_of(s):
        return os.path.join(clips_dir, s["id"] + ".mp4")
    jobs, todo = {}, []
    for s in shots:
        if s.get("type", "clip") not in CLIP_TYPES:
            continue
        jobs[s["id"]] = pending(p, out_of(s))
        if jobs[s["id"]]:              # a paid job from an earlier run: collect it, never skip it
            todo.append(s)
            continue
        if a.only and s["id"] not in a.only:
            continue
        if not draft and not a.only and not a.redo and os.path.exists(out_of(s)):
            continue                   # (a draft is only priced, so every shot in it counts)
        todo.append(s)
    if not todo:
        print("Nothing to make: every clip already exists (use --only or --redo to make new takes).")
        return
    default_q = a.quality or data.get("quality") or cfg.get("quality", "standard")
    model = a.model or cfg.get("model")
    longest = cfg.get("max_seconds", 8)
    problems = []
    vo = voiceover_file(a.project, data) if a.fit else None
    if vo and not os.path.isfile(vo):
        problems.append(f"the voiceover {os.path.relpath(vo, a.project)} doesn't exist (--fit needs its length "
                        f"for the last shot)")
        vo = None
    vo_len = duration(vo) if vo else 0    # as edit.py: an avatar video is the voiceover when there's no "vo"

    def num(s, k):
        v = s.get(k, 0)
        return v if isinstance(v, (int, float)) else 0

    def need(s):
        end = max(num(s, "end"), vo_len) if s is shots[-1] else num(s, "end")   # the edit runs the last shot to the VO's end
        return max(0.0, end - num(s, "start") + num(s, "in"))

    def length(s):
        """(seconds to ask for, spare seconds on top) for one clip."""
        if not a.fit:
            return longest, 0.0
        n = min(longest, need(s))
        return n, max(0.0, min(FIT_MARGIN, longest - n))

    def ask(fn, s):
        """seconds (and margin) for an adapter call: one that takes `margin` adds the spare second only when
        its allowed lengths leave too little room (a 3.1s shot stays a 4s Veo clip, not 6s)."""
        n, spare = length(s)
        if "margin" in inspect.signature(fn).parameters:
            return {"seconds": n, "margin": spare}
        return {"seconds": n + min(spare, FIT_PAD)}

    no_prompt = []
    for s in todo:
        if jobs[s["id"]]:
            continue
        if not str(s.get("video_prompt") or "").strip():
            no_prompt.append(s["id"])
        if s.get("frame"):
            problems.append(file_problem(os.path.join(a.project, s["frame"]), s["frame"], f"{s['id']}: frame"))
        problems.append(quality_problem(p, "video", s.get("quality", default_q), model, s["id"]))
        if a.fit and not all(isinstance(s.get(k), (int, float)) for k in ("start", "end")):
            problems.append(f'{s["id"]}: needs a "start" and an "end" (in seconds) for --fit')
    if no_prompt and len(no_prompt) == len([s for s in todo if not jobs[s["id"]]]) and draft:
        problems.append(f"{a.shots} is a draft with no video prompts: it can only be priced. Write shots.json "
                        f"(the shot plan) to make the clips.")
    elif no_prompt:
        problems.append(f"no video_prompt yet on {', '.join(no_prompt)}: write them in {a.shots} first")
    if mode != "api":
        stop_on(problems)
        for s in todo:   # one instruction file per clip, then hand over
            n, spare = length(s)
            extra = {"at least": f"{math.ceil(n * 10 - 1e-6) / 10:g}s"} if a.fit and spare else {}
            try:
                handoff(mode, "video", cfg, out_of(s), s["video_prompt"],
                        [os.path.join(a.project, s["frame"])] if s.get("frame") else [],
                        {"aspect ratio": "9:16", "length": length_for_tool(n + min(spare, FIT_PAD)), **extra,
                         "sound": "on" if s.get("type") == "talking" else "off (mute it)"},
                        s.get("quality", default_q), model)
            except SystemExit:
                continue
        sys.exit(3 if mode == "mcp" else 4)

    if a.fit and same_price_any_length(p, default_q, model):
        print(f"{p.label.split(' (')[0]} charges the same for any clip length, so --fit saves nothing here "
              f"(the edit trims each clip to its shot).")
    for s in todo:
        if s.get("clip") and os.path.normpath(os.path.join(a.project, s["clip"])) != os.path.normpath(out_of(s)):
            print(f"{s['id']} plays {s['clip']} in the edit: a new clips/{s['id']}.mp4 needs generate.py lipsync "
                  f"again (priced on its own), or the edit keeps the old take.")

    def price(s):
        q = s.get("quality", default_q)
        if jobs[s["id"]]:
            return finishing(f'{s["id"]} ({q})', jobs[s["id"]]), 0.0
        est = None
        if q in QUALITIES:
            est = p.estimate("video", q, model=model, audio=s.get("type") == "talking", **ask(p.estimate, s))
        return f'{s["id"]} ({q})', est
    project = os.path.abspath(a.project)
    confirm([price(s) for s in todo], a.yes, project=project, problems=[key_problem(p)] + problems)

    def one(s):
        out = out_of(s)
        os.makedirs(clips_dir, exist_ok=True)
        keep_old(out)
        frame = os.path.join(a.project, s["frame"]) if s.get("frame") else None
        r = p.video(s.get("video_prompt", ""), out, frame=frame, quality=s.get("quality", default_q),
                    audio=s.get("type") == "talking", model=model, **ask(p.video, s))
        if s.get("clip") and os.path.normpath(os.path.join(a.project, s["clip"])) != os.path.normpath(out):
            r.note += (f" | the edit still plays {s['clip']}: run generate.py lipsync on this new take "
                       f"(or remove \"clip\" from {s['id']} to play it as it is)")
        return r
    run_parallel(todo, one, f"{p.name}-video", out=out_of, label=lambda s: s["id"], project=project, p=p)


def cmd_voice(a):
    stop_on([file_problem(a.text_file, a.text_file, "--text-file")])
    with open(a.text_file, encoding="utf-8") as f:
        text = " ".join(l.strip() for l in f if l.strip())   # one block: blank lines make long pauses
    mode, p, cfg = route("voice", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        stop_on([None if text else f"{a.text_file} is empty: put the script in it"])
        handoff(mode, "voice", cfg, a.out, text, (), {"voice": a.voice or cfg.get("voice_id", "pick one"),
                                                      "language": a.language or "the script's language"}, quality,
                a.model or cfg.get("model"))
    project = find_project(a.out)
    voice_id = a.voice or cfg.get("voice_id")
    model = a.model or cfg.get("model") or p.model_for("voice", quality)
    job = pending(p, a.out)
    label = os.path.basename(a.out)
    est = p.estimate("voice", quality, model=model, chars=len(text)) if quality in QUALITIES else None
    plan = None if job or not text or not p.has_key() else p.describe("voice", chars=len(text), model=model)
    if plan:                           # ElevenLabs bills plan characters, not dollars: say what this uses
        print(f"  {plan}")
    confirm([(finishing(label, job), 0.0) if job else (label, est)], a.yes, project=project, problems=[
        f"not enough ElevenLabs characters left this month ({plan})" if plan and "NOT ENOUGH" in plan else None,
        key_problem(p), quality_problem(p, "voice", quality, model, "--quality"),
        None if text or job else f"{a.text_file} is empty: put the script in it",
        None if voice_id or job else "no voice chosen: list them with generate.py voices, then pass --voice <id> "
                                     "(or save one with check_setup.py --voice-id <id>)"])

    def one(o):
        os.makedirs(os.path.dirname(os.path.abspath(o)), exist_ok=True)
        keep_old(o)
        r = p.voice(text, o, voice_id, model=model, settings={"language": a.language} if a.language else None)
        r.note = f"{r.note}, {len(text):,} characters, {mmss(duration(o))} long"
        return r
    run_parallel([a.out], one, f"{p.name}-voice", project=project, p=p)


def cmd_lipsync(a):
    stop_on([file_problem(a.video, a.video, "--video"), file_problem(a.audio, a.audio, "--audio")])
    mode, p, cfg = route("lipsync", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "lipsync", cfg, a.out, None, [a.video, a.audio],
                {"job": "make the person in the video say the attached voiceover (keep the video's movement)"},
                quality, a.model)
    project = find_project(a.out)
    job = pending(p, a.out)
    # The lip-synced clip is as long as the line. Lip-sync and avatar share a slot, so only --model picks the model.
    est = p.estimate("lipsync", quality, seconds=duration(a.audio), model=a.model) if quality in QUALITIES else None
    confirm([(finishing(os.path.basename(a.out), job), 0.0) if job else (os.path.basename(a.out), est)], a.yes,
            project=project, problems=[key_problem(p), quality_problem(p, "lipsync", quality, a.model, "--quality")])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.lipsync(a.video, a.audio, o, quality=quality, model=a.model), f"{p.name}-lipsync",
                 project=project, p=p)


def cmd_avatar(a):
    stop_on([file_problem(a.image, a.image, "--image"), file_problem(a.audio, a.audio, "--audio")])
    mode, p, cfg = route("lipsync", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "lipsync", cfg, a.out, a.prompt, [a.image, a.audio],
                {"job": "turn the photo into a talking video that says the attached voiceover"}, quality, a.model)
    project = find_project(a.out)
    job = pending(p, a.out)
    talk = duration(a.audio)
    label = f"{os.path.basename(a.out)} ({mmss(talk)} of talking)"
    est = p.estimate("avatar", quality, seconds=talk, model=a.model) if quality in QUALITIES else None
    confirm([(finishing(label, job), 0.0) if job else (label, est)], a.yes, project=project,
            problems=[key_problem(p), quality_problem(p, "avatar", quality, a.model, "--quality")])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.avatar(a.image, a.audio, o, prompt=a.prompt or "", quality=quality, model=a.model),
                 f"{p.name}-avatar", project=project, p=p)


def cmd_music(a):
    mode, p, cfg = route("music", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "music", cfg, a.out, a.prompt + " Instrumental, no vocals.", (),
                {"length": length_for_tool(a.seconds) if a.seconds else "at least as long as the ad",
                 "vocals": "none (instrumental)"}, quality, a.model or cfg.get("model"))
    project = find_project(a.out)
    model = a.model or cfg.get("model") or p.model_for("music", quality)
    job = pending(p, a.out)
    est = p.estimate("music", quality, seconds=a.seconds, model=model) if quality in QUALITIES else None
    confirm([(finishing(os.path.basename(a.out), job), 0.0) if job else (os.path.basename(a.out), est)], a.yes,
            project=project, problems=[key_problem(p), quality_problem(p, "music", quality, model, "--quality")])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.music(a.prompt, o, seconds=a.seconds, model=model), f"{p.name}-music",
                 project=project, p=p)


def cmd_voices(a):
    mode, p, cfg = route("voice", a.provider)
    if mode != "api":
        sys.exit(f"Voice slot is '{mode}': pick the voice in that tool.")
    for vid, name, desc in p.voices():
        print(f"{vid}\t{name}\t{desc}")


def unit_price(p, slot, quality, model, longest=8):
    """One tier's price in the unit that slot is planned in (an image, a clip, 1,000 characters, ...)."""
    def est(**kw):
        return price_of(p, slot, quality, model=model, **kw)

    def usd(c, unit=""):
        return "cost unknown" if c is None else f"${c:.3f}{unit}"
    if slot == "image":
        return usd(est(), " per image")
    if slot == "video":
        lens = sorted({x for x in (4, 6, 8) if x < longest} | {longest})
        prices = [est(seconds=x) for x in lens]
        talk = est(seconds=longest, audio=True)
        if len(set(prices)) == 1:
            txt = usd(prices[0], f" per clip, any length up to {longest:g}s")
        else:
            txt = "  ".join(f"{x:g}s {usd(c)}" for x, c in zip(lens, prices))
        return txt + (f"  (with sound, for talking shots: {longest:g}s {usd(talk)})" if talk != prices[-1] else "")
    if slot == "voice":
        return usd(est(chars=1000), " per 1,000 characters")
    if slot == "music":
        return usd(est(seconds=60), " per 60s track")
    return usd(est(seconds=10), " per 10s of talking")      # lipsync, avatar


def cmd_prices(a):
    """Unit prices for every slot and tier, from the adapters: for the pace and rough-cost questions before any
    plan or jobs file exists. Free: nothing is made."""
    s = load_settings()
    print("Prices per unit in USD, from the provider's published rates (multiply by the number of clips, frames...).")
    print("Before each paid run, quote the estimate generate.py prints, not these.")
    for slot in SLOTS + ("avatar",):
        home = "lipsync" if slot == "avatar" else slot     # avatars share the lip-sync slot
        cfg = s.get(home, {})
        if a.provider:
            p = providers.get(a.provider)
            if home not in p.slots:
                continue
            if a.provider != cfg.get("provider"):
                cfg = {k: v for k, v in cfg.items() if k == "max_seconds"}
        elif cfg.get("mode", "none") != "api":
            mode = cfg.get("mode", "none")
            print(f"\n{slot:8} " + {"mcp": f"MCP ({cfg.get('tool', '?')}): price it with the tool itself "
                                            f"(e.g. get_cost: true)",
                                     "manual": f"by hand ({cfg.get('tool') or 'your own app'}): priced in that app"}
                  .get(mode, "not set yet: run check_setup.py"))
            continue
        else:
            try:
                p = providers.get(cfg.get("provider", ""))
            except providers.ProviderError as e:
                print(f"\n{slot:8} {e}. Choose again with check_setup.py --set {home}=api:<name>")
                continue
        pinned = None if home == "lipsync" else cfg.get("model")
        longest = cfg.get("max_seconds", 8)
        mine = cfg.get("quality", "standard")
        note = ""
        if slot == "video" and any(price_of(p, "video", q, seconds=2, model=pinned) is not None
                                   and not same_price_any_length(p, q, pinned) for q in QUALITIES):
            note = "  (billed per second: clips --fit asks for each shot's own length plus a spare second)"
        print(f"\n{slot:8} {p.label.split(' (')[0]}" + (f", pinned model {pinned}" if pinned else "") + note)
        models = {q: p.model_for(slot, q, pinned) or "-" for q in QUALITIES}
        w = max(len(m) for m in models.values())
        for q, m in models.items():
            print(f"  {q:9} {m:{w}}  {unit_price(p, slot, q, pinned, longest)}" + ("   <- your default" if q == mine else ""))
    print("\n'cost unknown' = no published price to work from: the real cost shows after the job when the provider "
          "reports it.")


def cmd_spend(a):
    """What each ad has cost so far (spend_log.csv), per project and per slot. Free."""
    want = project_name(a.project) if a.project else None
    by = {}
    for r in spend_rows():
        proj = r.get("project") or "(no project)"
        if want and proj != want:
            continue
        tool = (r.get("what") or "?").split()[0]
        slot = tool.split("-", 1)[1] if "-" in tool else tool      # "kie-image a.png" -> image
        t = by.setdefault(proj, {}).setdefault(slot, [0.0, 0, 0])    # usd, jobs, jobs of unknown cost
        t[1] += 1
        try:
            t[0] += float(r["usd"])
        except (TypeError, ValueError):
            t[2] += 1
    if not by:
        print(f"Nothing spent on {want} yet." if want else f"Nothing spent yet ({SPEND_LOG} is empty or missing).")
        return
    for proj, slots in by.items():
        usd, unknown = sum(v[0] for v in slots.values()), sum(v[2] for v in slots.values())
        budget = load_budget(a.project) if want and os.path.isdir(a.project) else None
        print(f"{proj}: ${usd:.2f}" + (f" of your ${budget:.2f} budget" if budget else "")
              + (f" (plus {unknown} job(s) of unknown cost)" if unknown else ""))
        for slot, (u, n, k) in sorted(slots.items()):
            cost = "cost unknown" if k == n else "$%.2f" % u
            print(f"  {slot:8} {cost:>12}  {n} job(s)" + (f", {k} of unknown cost" if k and k < n else ""))


def run_parallel(items, fn, what, out=lambda it: it, label=None, project=None, p=None):
    """Runs fn on every item (4 at a time), logs what each one cost, and says what to do about failures.
    out(item) = the file the item writes; label(item) = its name in messages (the file name by default);
    p = the adapter, to tell a job the provider still has (a re-run collects it) from one that's gone."""
    label = label or (lambda it: os.path.basename(out(it)))
    failed, maybe_paid, resumable, refused = 0, [], [], False
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for f in cf.as_completed(futs):
            if f.cancelled():
                continue
            it = futs[f]
            name = label(it)
            try:
                r = f.result()
            except providers.OutOfCredit as e:
                print(f"{name}: STOPPED, {e}", flush=True)
                failed += 1
                for other in futs:             # don't start the jobs still waiting: they'd fail the same way
                    if not other.done() and other.cancel():
                        print(f"{label(futs[other])}: not started (out of credit)", flush=True)
                        failed += 1
                continue
            except providers.ProviderError as e:
                print(f"{name}: FAILED, {e}", flush=True)
                failed += 1
                if pending(p, out(it)):        # the provider has the job: a re-run collects it
                    resumable.append(name)
                elif any(w in str(e) for w in MAYBE_PAID):
                    maybe_paid.append(name)
                elif any(w in str(e).lower() for w in REFUSED):
                    refused = True
                continue
            except FileNotFoundError as e:
                print(f"{name}: FAILED, missing file {e.filename}", flush=True)
                failed += 1
                continue
            except Exception as e:
                print(f"{name}: FAILED, {type(e).__name__}: {e}", flush=True)
                failed += 1
                continue
            log_spend(f"{what} {name}" + ("" if r.cost is not None else f" ({r.note})"), r.cost, project)
            cost = f"${r.cost:.3f}" if r.cost is not None else "cost unknown"
            print(f"{name}: saved {r.files[0]} ({r.note}, {cost})", flush=True)
    show_spent(project)
    if failed:
        msg = [f"{failed} job(s) failed."]
        if resumable:
            msg.append(f"{', '.join(resumable)}: the provider still has the job, so running the same command again "
                       f"collects it instead of paying for a new one.")
        if maybe_paid:
            msg.append(f"{', '.join(maybe_paid)} may have been made and charged anyway: check the provider before "
                       f"running {'it' if len(maybe_paid) == 1 else 'them'} again.")
        if failed > len(maybe_paid) + len(resumable):
            msg.append(("The others are" if maybe_paid or resumable else "Failed jobs are") + " normally not charged.")
            if refused:
                msg.append("If it was a safety filter, soften the prompt (often a person + a medical detail) and retry.")
        print(" ".join(msg))
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--provider", help="force an API adapter, e.g. kie")
        sp.add_argument("--model", help="exact model id (overrides quality)")
        sp.add_argument("--yes", action="store_true", help="actually run paid jobs")

    i = sub.add_parser("image"); common(i)
    i.add_argument("--prompt"); i.add_argument("--prompt-file"); i.add_argument("--out", required=True)
    i.add_argument("--ref", action="append", default=[]); i.add_argument("--n", type=int, default=1)
    i.add_argument("--aspect", default="9:16"); i.add_argument("--quality", choices=("draft", "standard", "best"))

    ims = sub.add_parser("images"); common(ims)
    ims.add_argument("jobs", help='JSON list of {"prompt", "out", "refs": [], "aspect", "quality"}')
    ims.add_argument("--quality", choices=("draft", "standard", "best"))
    ims.add_argument("--only", nargs="*", help="remake these (s03 or s03.png), even if they exist")
    ims.add_argument("--redo", action="store_true", help="remake every image, even the ones that exist")

    v = sub.add_parser("video"); common(v)
    v.add_argument("--prompt"); v.add_argument("--prompt-file"); v.add_argument("--out", required=True)
    v.add_argument("--frame"); v.add_argument("--aspect", default="9:16"); v.add_argument("--audio", action="store_true")
    v.add_argument("--seconds", type=float, help="clip length (default: max_seconds from providers.json, 8)")
    v.add_argument("--quality", choices=("draft", "standard", "best"))

    c = sub.add_parser("clips"); common(c)
    c.add_argument("project"); c.add_argument("--shots", default="shots.json")
    c.add_argument("--only", nargs="*"); c.add_argument("--redo", action="store_true")
    c.add_argument("--fit", action="store_true", help="ask for each shot's own length (+1s), not max_seconds")
    c.add_argument("--quality", choices=("draft", "standard", "best"))

    vo = sub.add_parser("voice"); common(vo)
    vo.add_argument("--text-file", required=True); vo.add_argument("--out", required=True); vo.add_argument("--voice")
    vo.add_argument("--language", help="the script's language code, e.g. fr (some voice models assume English)")
    vo.add_argument("--quality", choices=("draft", "standard", "best"))

    vs = sub.add_parser("voices"); vs.add_argument("--provider")

    mu = sub.add_parser("music"); common(mu)
    mu.add_argument("--prompt", required=True); mu.add_argument("--out", required=True)
    mu.add_argument("--seconds", type=float, help="track length, at least as long as the ad (provider default if unset)")
    mu.add_argument("--quality", choices=("draft", "standard", "best"))

    ls = sub.add_parser("lipsync"); common(ls)
    ls.add_argument("--video", required=True); ls.add_argument("--audio", required=True)
    ls.add_argument("--out", required=True); ls.add_argument("--quality", choices=("draft", "standard", "best"))

    av = sub.add_parser("avatar"); common(av)
    av.add_argument("--image", required=True); av.add_argument("--audio", required=True)
    av.add_argument("--out", required=True); av.add_argument("--prompt")
    av.add_argument("--quality", choices=("draft", "standard", "best"))

    pr = sub.add_parser("prices", help="price per unit for every slot and tier (free)")
    pr.add_argument("--provider", help="show this adapter's prices instead of the slots' own")

    sp = sub.add_parser("spend", help="what each ad has cost so far (free)")
    sp.add_argument("project", nargs="?", help="one project folder (e.g. .), else every project")

    a = ap.parse_args()
    if a.cmd in ("image", "video") and not (a.prompt or a.prompt_file):
        ap.error("--prompt or --prompt-file is required")
    if a.cmd == "image" and a.n < 1:
        ap.error("--n must be 1 or more")
    try:
        {"image": cmd_image, "images": cmd_images, "video": cmd_video, "clips": cmd_clips, "voice": cmd_voice,
         "voices": cmd_voices, "lipsync": cmd_lipsync, "avatar": cmd_avatar, "music": cmd_music,
         "prices": cmd_prices, "spend": cmd_spend}[a.cmd](a)
    except providers.ProviderError as e:
        sys.exit(f"ERROR: {e}")
    except FileNotFoundError as e:
        sys.exit(f"ERROR: {e.filename or e} doesn't exist.")


if __name__ == "__main__":
    main()
