"""One entry point for every generation. Routes each job to the tool set for its slot in providers.json.

    generate.py image  --prompt "..." --out frames/s01.png [--ref sheet.png] [--n 3] [--quality draft|standard|best]
    generate.py images jobs.json                          # several different images, one cost, one approval
    generate.py video  --prompt "..." --out clips/s01.mp4 [--frame frames/s01.png] [--audio] [--seconds 6]
    generate.py clips  <project> [--shots shots.json] [--only s03 s07] [--redo] [--fit]
    generate.py voice  --text-file script.txt --out audio/vo.mp3 --voice <voice id>
    generate.py voices                                    # list voices to pick from (free)
    generate.py lipsync --video clips/s04.mp4 --audio audio/s04.mp3 --out clips/s04_talk.mp4
    generate.py avatar  --image frames/host.png --audio audio/vo.mp3 --out clips/host.mp4 [--prompt "..."]
    generate.py music   --prompt "..." --out inputs/music.mp3 [--seconds 60]

Paid jobs print the estimate and stop; add --yes to run them. --provider <name> forces an API adapter.
Clips are --seconds long (default: the video slot's max_seconds, 8). `clips --fit` asks for each shot's own length
plus a spare second instead, which costs less on providers that bill per second (Replicate, Higgsfield).

Slot modes (providers.json):
  api     run it here with the adapter
  mcp     exit 3: Claude calls the MCP tool itself and saves the file to --out
  manual  exit 4: writes manual/<name>.md with everything the user needs to run it by hand
  none    exit 2: no tool chosen yet, run check_setup.py
"""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers
from common import check_spend, duration, load_settings, log_spend, mmss

CLIP_TYPES = ("clip", "veo", "talking")      # shot types that need a generated clip ("veo" = old name)
FIT_MARGIN = 1.0                             # --fit: a spare second per clip for trims and small re-timings


def route(slot, forced=None):
    """Returns ("api", adapter, cfg) or exits with the right code for mcp / manual / none."""
    cfg = load_settings().get(slot, {})
    if forced:
        p = providers.get(forced)
        if slot not in p.slots:
            sys.exit(f"{p.label} can't do {slot}. It does: {', '.join(p.slots)}")
        return "api", p, cfg
    mode = cfg.get("mode", "none")
    if mode == "api":
        return "api", providers.get(cfg.get("provider", "")), cfg
    if mode in ("mcp", "manual"):
        return mode, None, cfg
    print(f"No tool is set for {slot}. Run: python3 scripts/check_setup.py")
    sys.exit(2)


def handoff(mode, slot, cfg, out, prompt=None, refs=(), settings=None):
    """MCP or manual: describe the job instead of running it."""
    if mode == "mcp":
        print(f"MCP: call the tool '{cfg.get('tool', '?')}' for this {slot} job, then save the result to {out}")
        print(json.dumps({"prompt": prompt, "refs": list(refs), **(settings or {})}, indent=2))
        sys.exit(3)
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(out))) or ".", "manual")
    os.makedirs(folder, exist_ok=True)
    note = os.path.join(folder, os.path.splitext(os.path.basename(out))[0] + f"_{slot}.md")
    lines = [f"# {slot.title()} job: {os.path.basename(out)}", "",
             f"Run this in your {slot} tool ({cfg.get('tool') or 'any tool you like'}).", ""]
    for k, v in (settings or {}).items():
        lines.append(f"- **{k}:** {v}")
    if refs:
        lines += ["", "**Attach these files, in this order:**"] + [f"{i}. `{r}`" for i, r in enumerate(refs, 1)]
    if prompt:
        lines += ["", "**Prompt (copy all of it):**", "", "```", prompt, "```"]
    lines += ["", f"**Save the result as:** `{os.path.abspath(out)}`", ""]
    with open(note, "w") as f:
        f.write("\n".join(lines))
    print(f"MANUAL: instructions written to {note}")
    print(f"Waiting for the file at {out}")
    sys.exit(4)


def confirm(items, yes):
    """items = list of (label, usd or None). Prints the estimate; stops unless --yes."""
    known = [c for _, c in items if c is not None]
    for label, c in items:
        print(f"  {label:40} {'$%.3f' % c if c is not None else 'cost unknown'}")
    total = sum(known)
    if known:
        print(f"{len(items)} job(s), about ${total:.2f}" + (" (some costs unknown)" if len(known) < len(items) else ""))
    else:
        print(f"{len(items)} job(s), cost unknown (the provider doesn't report prices)")
    check_spend(total)
    if not yes:
        print("Estimate only. Re-run with --yes to generate.")
        sys.exit(0)


def keep_old(out):
    if os.path.exists(out):
        base, ext = os.path.splitext(out)
        shutil.move(out, f"{base}_prev{ext}")


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


def cmd_image(a):
    prompt = open(a.prompt_file).read().strip() if a.prompt_file else a.prompt
    mode, p, cfg = route("image", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "image", cfg, a.out, prompt, a.ref, {"aspect ratio": a.aspect, "takes": a.n})
    base, ext = os.path.splitext(a.out)
    outs = [a.out] if a.n == 1 else [f"{base}_{i + 1}{ext or '.png'}" for i in range(a.n)]
    est = p.estimate("image", quality, model=a.model or cfg.get("model"))
    confirm([(os.path.basename(o), est) for o in outs], a.yes)

    run_parallel(outs, lambda o: make_image(p, prompt, o, a.ref, a.aspect, quality, a.model or cfg.get("model")),
                 f"{p.name}-image")


def make_image(p, prompt, o, refs, aspect, quality, model):
    os.makedirs(os.path.dirname(os.path.abspath(o)), exist_ok=True)
    r = p.image(prompt, o, refs=refs, aspect=aspect, quality=quality, model=model)
    if looks_banded(o) and quality != "best" and not model:
        # Image models sometimes letterbox a tall frame. Remake once on the best model.
        base_, ext_ = os.path.splitext(o)
        os.replace(o, f"{base_}_banded{ext_}")
        log_spend(f"{p.name}-image {os.path.basename(o)} (banded, remade)", r.cost)
        r = p.image(prompt, o, refs=refs, aspect=aspect, quality="best")
        r.note += " (remade on best: first take had bands)"
    if looks_banded(o):
        r.note += " | CHECK: may still have bands, look at it"
    return r


def cmd_images(a):
    """Several different images (character options, a set of frames) priced and approved together."""
    with open(a.jobs) as f:
        jobs = json.load(f)
    root = os.path.dirname(os.path.abspath(a.jobs))

    def at(path):
        return path if os.path.isabs(path) else os.path.join(root, path)
    for j in jobs:
        j["out"] = at(j["out"])
        j["refs"] = [at(r) for r in j.get("refs", [])]
        if j.get("prompt_file"):
            j["prompt"] = open(at(j["prompt_file"])).read().strip()
    mode, p, cfg = route("image", a.provider)
    if mode != "api":
        for j in jobs:         # one instruction file per image, then hand over
            try:
                handoff(mode, "image", cfg, j["out"], j["prompt"], j["refs"], {"aspect ratio": j.get("aspect", "9:16")})
            except SystemExit:
                continue
        sys.exit(3 if mode == "mcp" else 4)
    model = a.model or cfg.get("model")
    default_q = a.quality or cfg.get("quality", "standard")
    confirm([(os.path.basename(j["out"]), p.estimate("image", j.get("quality", default_q), model=model)) for j in jobs],
            a.yes)
    run_parallel(jobs, lambda j: make_image(p, j["prompt"], j["out"], j["refs"], j.get("aspect", "9:16"),
                                            j.get("quality", default_q), model),
                 f"{p.name}-image", label=lambda j: os.path.basename(j["out"]))


def cmd_video(a):
    prompt = open(a.prompt_file).read().strip() if a.prompt_file else a.prompt
    mode, p, cfg = route("video", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "video", cfg, a.out, prompt, [a.frame] if a.frame else [],
                {"aspect ratio": a.aspect, "length": f"{cfg.get('max_seconds', 8)}s",
                 "start frame": a.frame or "none", "sound": "on" if a.audio else "off (mute it)"})
    seconds = a.seconds or cfg.get("max_seconds", 8)
    confirm([(os.path.basename(a.out), p.estimate("video", quality, seconds=seconds, model=a.model or cfg.get("model"),
                                                  audio=a.audio))], a.yes)

    def one(o):
        os.makedirs(os.path.dirname(os.path.abspath(o)), exist_ok=True)
        keep_old(o)
        return p.video(prompt, o, frame=a.frame, seconds=seconds, aspect=a.aspect, quality=quality, audio=a.audio,
                       model=a.model or cfg.get("model"))
    run_parallel([a.out], one, f"{p.name}-video")


def cmd_clips(a):
    with open(os.path.join(a.project, a.shots)) as f:
        data = json.load(f)
    mode, p, cfg = route("video", a.provider)
    clips_dir = os.path.join(a.project, "clips")
    todo = []
    for s in data["shots"]:
        if s.get("type", "clip") not in CLIP_TYPES:
            continue
        if a.only and s["id"] not in a.only:
            continue
        if not a.only and not a.redo and os.path.exists(os.path.join(clips_dir, s["id"] + ".mp4")):
            continue
        todo.append(s)
    if not todo:
        print("Nothing to make: every clip already exists (use --only or --redo to make new takes).")
        return
    if mode != "api":
        for s in todo:   # one instruction file per clip, then hand over
            try:
                handoff(mode, "video", cfg, os.path.join(clips_dir, s["id"] + ".mp4"), s["video_prompt"],
                        [os.path.join(a.project, s["frame"])] if s.get("frame") else [],
                        {"aspect ratio": "9:16", "length": f"{cfg.get('max_seconds', 8)}s",
                         "sound": "on" if s.get("type") == "talking" else "off (mute it)"})
            except SystemExit:
                continue
        sys.exit(3 if mode == "mcp" else 4)

    default_q = a.quality or data.get("quality") or cfg.get("quality", "standard")
    model = a.model or cfg.get("model")
    longest = cfg.get("max_seconds", 8)
    vo_len = duration(os.path.join(a.project, data["vo"])) if a.fit and data.get("vo") else 0

    def seconds(s):
        if not a.fit:
            return longest
        end = max(s["end"], vo_len) if s is data["shots"][-1] else s["end"]   # the edit runs the last shot to the VO's end
        return min(longest, end - s["start"] + s.get("in", 0) + FIT_MARGIN)
    confirm([(f'{s["id"]} ({s.get("quality", default_q)})',
              p.estimate("video", s.get("quality", default_q), seconds=seconds(s), model=model,
                         audio=s.get("type") == "talking")) for s in todo], a.yes)

    def one(s):
        out = os.path.join(clips_dir, s["id"] + ".mp4")
        os.makedirs(clips_dir, exist_ok=True)
        keep_old(out)
        frame = os.path.join(a.project, s["frame"]) if s.get("frame") else None
        return p.video(s["video_prompt"], out, frame=frame, seconds=seconds(s), quality=s.get("quality", default_q),
                       audio=s.get("type") == "talking", model=model)
    run_parallel(todo, one, f"{p.name}-video", label=lambda s: s["id"], project=a.project)


def cmd_voice(a):
    text = " ".join(l.strip() for l in open(a.text_file) if l.strip())   # one block: blank lines make long pauses
    mode, p, cfg = route("voice", a.provider)
    if mode != "api":
        handoff(mode, "voice", cfg, a.out, text, (), {"voice": a.voice or cfg.get("voice_id", "pick one"),
                                                      "model": a.model or cfg.get("model", "the most natural one"),
                                                      "language": a.language or "the script's language"})
    voice_id = a.voice or cfg.get("voice_id")
    if not voice_id:
        sys.exit("No voice chosen. List them with: generate.py voices")
    model = a.model or cfg.get("model") or p.model_for("voice", cfg.get("quality", "standard"))
    confirm([(os.path.basename(a.out), p.estimate("voice", cfg.get("quality", "standard"), model=model,
                                                  chars=len(text)))], a.yes)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    r = p.voice(text, a.out, voice_id, model=model, settings={"language": a.language} if a.language else None)
    print(f"saved {a.out}  ({mmss(duration(a.out))})")
    log_spend(f"{p.name}-voice", r.cost)


def cmd_lipsync(a):
    mode, p, cfg = route("lipsync", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "lipsync", cfg, a.out, None, [a.video, a.audio],
                {"job": "make the person in the video say the attached voiceover (keep the video's movement)"})
    # The lip-synced clip is as long as the line. Lip-sync and avatar share a slot, so only --model picks the model.
    confirm([(os.path.basename(a.out), p.estimate("lipsync", quality, seconds=duration(a.audio), model=a.model))], a.yes)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.lipsync(a.video, a.audio, o, quality=quality, model=a.model), f"{p.name}-lipsync")


def cmd_avatar(a):
    mode, p, cfg = route("lipsync", a.provider)
    quality = a.quality or cfg.get("quality", "standard")
    if mode != "api":
        handoff(mode, "lipsync", cfg, a.out, a.prompt, [a.image, a.audio],
                {"job": "turn the photo into a talking video that says the attached voiceover"})
    talk = duration(a.audio)
    confirm([(f"{os.path.basename(a.out)} ({mmss(talk)} of talking)",
              p.estimate("avatar", quality, seconds=talk, model=a.model))], a.yes)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.avatar(a.image, a.audio, o, prompt=a.prompt or "", quality=quality, model=a.model),
                 f"{p.name}-avatar")


def cmd_music(a):
    mode, p, cfg = route("music", a.provider)
    if mode != "api":
        handoff(mode, "music", cfg, a.out, a.prompt + " Instrumental, no vocals.", (),
                {"length": "at least as long as the ad", "vocals": "none (instrumental)"})
    model = a.model or cfg.get("model") or p.model_for("music", cfg.get("quality", "standard"))
    confirm([(os.path.basename(a.out), p.estimate("music", cfg.get("quality", "standard"), seconds=a.seconds,
                                                  model=model))], a.yes)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    keep_old(a.out)
    run_parallel([a.out], lambda o: p.music(a.prompt, o, seconds=a.seconds, model=model), f"{p.name}-music")


def cmd_voices(a):
    mode, p, cfg = route("voice", a.provider)
    if mode != "api":
        sys.exit(f"Voice slot is '{mode}': pick the voice in that tool.")
    for vid, name, desc in p.voices():
        print(f"{vid}\t{name}\t{desc}")


def run_parallel(items, fn, what, label=os.path.basename, project=""):
    failed = 0
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for f in cf.as_completed(futs):
            if f.cancelled():
                continue
            name = label(futs[f])
            try:
                r = f.result()
                log_spend(f"{what} {name}", r.cost, project)
                cost = f"${r.cost:.3f}" if r.cost is not None else "cost unknown"
                print(f"{name}: saved {r.files[0]} ({r.note}, {cost})", flush=True)
            except providers.OutOfCredit as e:
                print(f"{name}: STOPPED, {e}", flush=True)
                failed += 1
                for other in futs:             # don't start the jobs still waiting: they'd fail the same way
                    if other.cancel():
                        print(f"{label(futs[other])}: not started (out of credit)", flush=True)
                        failed += 1
            except Exception as e:
                print(f"{name}: FAILED, {e}", flush=True)
                failed += 1
    if failed:
        print(f"{failed} job(s) failed. Failed jobs are normally not charged. If it was a safety filter, "
              f"soften the prompt (often a person + a medical detail) and retry.")
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

    vs = sub.add_parser("voices"); vs.add_argument("--provider")

    mu = sub.add_parser("music"); common(mu)
    mu.add_argument("--prompt", required=True); mu.add_argument("--out", required=True)
    mu.add_argument("--seconds", type=float, help="track length, at least as long as the ad (provider default if unset)")

    ls = sub.add_parser("lipsync"); common(ls)
    ls.add_argument("--video", required=True); ls.add_argument("--audio", required=True)
    ls.add_argument("--out", required=True); ls.add_argument("--quality", choices=("draft", "standard", "best"))

    av = sub.add_parser("avatar"); common(av)
    av.add_argument("--image", required=True); av.add_argument("--audio", required=True)
    av.add_argument("--out", required=True); av.add_argument("--prompt")
    av.add_argument("--quality", choices=("draft", "standard", "best"))

    a = ap.parse_args()
    if a.cmd in ("image", "video") and not (a.prompt or a.prompt_file):
        ap.error("--prompt or --prompt-file is required")
    try:
        {"image": cmd_image, "images": cmd_images, "video": cmd_video, "clips": cmd_clips, "voice": cmd_voice, "voices": cmd_voices,
         "lipsync": cmd_lipsync, "avatar": cmd_avatar, "music": cmd_music}[a.cmd](a)
    except providers.ProviderError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
