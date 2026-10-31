---
name: ai-ad-editor
description: Turn a finished ad script into a finished short-form video ad (9:16, plus 4:5, 1:1 and 16:9 if wanted) from AI-generated clips, the user's own clip library (UGC), or both - voiceover, shot plan, library clip matching, characters, scene images, AI video clips, talking characters with lip-sync, edit, captions, music, hook variants, quality checks and export. Works with any generation tools - built for Kie.ai (images, video and lip-sync) with ElevenLabs for the voiceover, also Replicate (every slot) and Higgsfield (images and video by API, or its MCP), any other MCP or API, or by hand with copy-paste prompts. Nothing paid runs without your yes. Use when the user says "edit this ad", "make the video", "turn this script into an ad", "video ad from this script", "AI ad editor", "make hook variants", or brings a script (and maybe a voiceover or avatar clip) and wants a finished video ad.
---

# AI Ad Editor

Takes a finished script and makes the finished video ad. The script is never rewritten: the job starts at the voiceover.

**Three ways to get the pictures**, chosen in Step 1:
- **AI:** every clip is generated (images, AI video clips, AI talking avatars). All 10 steps.
- **Library (UGC):** every clip comes from the user's own folder of filmed clips. The skill picks and trims; nothing is generated, so it's free apart from an optional generated voiceover. Steps 6, 7 and 8 are skipped, so the user sees 7 steps (see Rule 14).
- **Mixed:** library first; any line with no good library clip is made with AI, matched to the library footage. Steps 6 to 8 run only for those shots.

`$S` = this skill's `scripts/` folder. Every script runs with `python3` (on Windows, use `python` instead). Run them from inside the project folder, so `<project>` in a command is `.` and every other path (`audio/vo.mp3`, `final/<file>.mp4`) is a path inside the project, written the same way as in `shots.json`. The library folder is the only path outside it: give its full path.

---

## Rules

1. **Say it, then wait for a yes** (every-step mode). Before every generation, show what will be made and the full prompt, then wait. In key steps and autopilot, the budget approved in Stage 0 is the yes for frames and clips: the estimate is still printed and the running total shown. On a re-run, show only what changed. "Go ahead and make it all" covers one batch, not the next stage.
2. **Never redo work on your own.** If a result has a problem, say what it is, suggest the fix, and wait.
3. **Choices are buttons.** Use `AskUserQuestion`: 2 to 4 options, one line each, the recommended one first and marked "(Recommended)". Taste and creative choices (music, voice, character, look, pace, hooks, how the product or explanation lines appear) get no recommendation: lay the options out evenly, with the cost next to any option that changes it. If the client has no buttons, use a short numbered list.
4. **Test one, then the rest** (every-step mode). One frame, then 1 or 2 clips, then the batch. In key steps and autopilot the batch is made in one run, checked on the contact sheet, and only failures are reported.
5. **Never touch the voiceover.** No speed change, no cuts inside it, no re-ordering. Clips are cut to fit the voiceover, never the other way round. A hook's voiceover is a new file made by `hook.py`; the main one is never changed.
6. **Never change clip speed** unless the user asks.
7. **Files, not chat.** Plans and prompts are saved in the project folder. In chat, give a short note of what changed and the file path. Show tables (shot plan, brief summary) in chat; they are short.
8. **Fix only what was flagged.** A revision changes only what the user named. Every change makes a new version number.
9. **Meta-safe visuals.** Nothing graphic or medical on screen (no wounds, needles, blood or surgery), even when the voiceover talks about them. Show the feeling through the person: their face, a pause, a look out of the window.
10. **Soft claims.** Any on-screen text the skill writes makes no cure or disease claims.
11. **Plain words** in every message and prompt.
12. **Costs only when known.** `generate.py` prints the estimate from the provider; for planning before any job exists, `python3 $S/generate.py prices` lists the unit prices (free). Never guess a price. Quote the estimate before every paid run and pass `--yes` only after the user agrees. `generate.py` checks everything a run needs first (API key, prompts and video prompts, frames, refs, input files, quality names) and lists every problem under the estimate; with `--yes` nothing runs until they're all fixed (exit 1). Fix them all, then re-run.
13. **API keys never go in chat.** Users add them to their shell profile themselves.
14. **Be a guide, not a form.** Walk the user through one step at a time, like a person sitting next to them:
    - Open every step with where they are and why it matters: `**Step 3 of 10: Voiceover.** The voiceover sets the timing for every shot, so we lock it first.` In library mode the steps are 1 to 7 (Setup, Brief, Voiceover, Timing, Pick the clips, Edit, Checks and delivery): say `Step 3 of 7`.
    - Ask one decision at a time, with buttons. Never dump a list of settings or a table of tools.
    - End every step with what was done and what comes next: `Done: voiceover approved (0:26). Next: I'll time every word so the cuts land on them.`
    - Explain any term the first time it comes up (start frame, lip-sync, 4:5 safe zone) in one short line.
    - Recommend only where there's a practical right answer (setup, cost, quality, safety). Creative and taste choices are laid out evenly. Always leave room for their own answer.
15. **Any concept, any look.** The skill makes whatever the ad needs: 3D animation, 2D cartoon, motion graphics, cinematic, photoreal phone footage, stop-motion style, anything else. Never assume a look; the user picks it in Step 2.
16. **Their process comes first.** Before anything else, read `house-rules.md` in the working folder if it exists. It holds how this user or team works: how hands-on they want to be, naming, where finished files go, caption style, default look and voice, who approves, things they never do. It overrides this skill's defaults and recommendations. It never overrides rules 5, 12 and 13 (the voiceover is never touched, no paid run without an approved cost, keys never in chat). When the user says something should always or never happen, add it to `house-rules.md` and say so in one line. The blank layout is in `house-rules-template.md`.

**The 10 steps the user sees:** 1 Setup · 2 Brief and look · 3 Voiceover · 4 Timing · 5 Shot plan and hooks · 6 Characters · 7 Start frames · 8 Clips · 9 Edit · 10 Variants, checks and delivery. (The stages below are numbered for this file; always show the user these step numbers.)

---

## Stage 00 — Setup (Step 1 of 10)

Free. Keep it short: the user wants to make an ad, not configure software.

1. Run `python3 $S/check_setup.py` quietly. Don't show its output.
2. **Already set up** (`providers.json` filled): one line naming what each slot uses, e.g. "You're set up with Kie, same as last time." Move on.
3. **First time:** say what's needed in plain words: "To make the images and clips I need one AI generation account. The easiest is a Kie.ai API key: one key and one balance for images, video and lip-sync." Then ask with buttons (the free "Other" answer covers another MCP or API, or running the prompts by hand):
   - **Kie.ai API key (Recommended).** If `KIE_API_KEY` works, confirm "Kie is connected, balance $X" and move on. If not, tell them how to get one and add it to their shell profile.
   - **Replicate API token.** Pay per result, every slot (images, video, voice, music, lip-sync, avatars). If `REPLICATE_API_TOKEN` works, confirm "Replicate is connected (account X)". Replicate shows no balance through its API: point them to replicate.com/account/billing. If not set, tell them to make a token at replicate.com/account/api-tokens and add it to their shell profile.
   - **Higgsfield.** Two ways, check both: the **API** (`HF_KEY="<key id>:<secret>"` from console.higgsfield.ai, API keys) makes images and video; the **Higgsfield MCP**, if it's connected in this Claude (tools named `mcp__higgsfield__*`), also does voiceovers and lip-sync, paid in Higgsfield credits (see "Higgsfield MCP" below). Neither makes music: that slot goes to another provider or by hand.
   - **Another tool or by hand.** An MCP they've connected, or another API key: check it and use it. Or manual mode: you write every prompt, they run it in any app.
4. Save it: `python3 $S/check_setup.py --auto` fills every empty slot from the keys that work (a working ElevenLabs key takes the voice slot; otherwise Kie first, then Replicate, then Higgsfield). Or set slots one by one: `--set image=api:replicate --set video=api:replicate --set lipsync=api:replicate`, `--set video=api:higgsfield`, `--set video=mcp:higgsfield`, `--set video=mcp:<tool name>`, `--set video=mcp:<tool>:<model>` (pins a model, printed with every handoff), `--set video=manual:<app>`. Slots can mix providers (e.g. Higgsfield video, Replicate music). Read what it prints:
   - `WARNING: <KEY> is not set` on a slot: `generate.py` will stop on that slot until the key is in their shell profile.
   - `Not filled: ...` after `--auto`: a provider has a key but it couldn't be checked, so its slots are left empty rather than given to a dearer one. Run `--auto` again, or choose with `--set`.
   - A saved voice the new voice provider doesn't have is dropped with a message: pick again in Step 3 (`generate.py voices`).
5. **Don't ask about voice, music or lip-sync now.** Each comes up in its own step, only if the ad needs it.
6. **Models are a choice, not a rule.** When clips come up (Step 8), recommend Veo 3.1 Fast as the place to start (good motion, fair price). `--quality draft|standard|best` picks the provider's model for each tier (table below); `check_setup.py --set video=api:<provider>:<model id>` pins any model the adapter knows (not on the lip-sync slot, which avatars share: there pass `--model <id>` to `generate.py lipsync` or `avatar` each run). On Kie, the built-in video models are the Veo 3.1 family (`veo3_lite`, `veo3_fast`, `veo3`); other Kie video models (Kling, Seedance and so on) need their own few lines in `scripts/providers/kie.py` before they work. Through an MCP or by hand, any model the user has works. Same for images: Nano Banana 2 to start (Nano Banana 2.1 on Replicate), any other image model if they prefer.
7. Only if ffmpeg or faster-whisper is missing, or ffmpeg is a cut-down build (no H.264 or no captions: `ffmpeg is missing libx264, ass...`), give the one install line `check_setup.py` prints. Setup isn't done until it passes: the edit can't run without them.

**How each mode works from here on.** Every generation goes through `generate.py`:

| Slot mode | What `generate.py` does | What you do |
|---|---|---|
| `api` | Prints the estimate; with `--yes` it makes the file | Quote the estimate, get a yes, re-run with `--yes` |
| `mcp` | Exits with code 3 and prints the prompt and settings | Call that MCP tool with them; save the result to the path it printed |
| `manual` | Exits with code 4 and writes `manual/<name>.md` | Tell the user which file to open; wait for them to drop the result where it says |

Every rule and approval stays the same in every mode. In manual mode, "approve" means approving the prompt before they run it.

**A run that's cut off is finished, not paid twice.** When the provider has taken a paid job and the run then times out, loses the connection or is killed, `generate.py` keeps the job id next to the file (`clips/s03.mp4.job.json`). Run the same command again: the estimate shows that item as `$0.00 (finishing job <id>)` and the run collects it. Run long batches (clips, lip-sync, avatars) with a long Bash timeout or in the background, and if one is killed anyway, just run it again. Never delete a `.job.json` file by hand.

**Which model each provider uses** (`--quality`, default standard):

| Slot | Kie | Replicate | Higgsfield API |
|---|---|---|---|
| image | Nano Banana / Nano Banana 2 / Nano Banana Pro | Nano Banana 2.1 1K / Nano Banana 2.1 2K / Nano Banana Pro | Qwen Image 3 1K / Qwen Image 3 2K / GPT Image 2.5 Flare |
| video | Veo 3.1 Lite / Fast / Full, always 8s | Seedance 1 Pro Fast / Veo 3.1 Fast / Veo 3.1, sound off, billed per second | Wan 3.0 720p / Wan 3.0 1080p / Kling 3.0 Pro, sound off, billed per second |
| voice | ElevenLabs v3 (fixed voice list) | ElevenLabs Turbo v2.5 / v3 / v3 (26 named voices) | none (MCP only) |
| music | Suno, 2 takes | Stable Audio 2.5 / ElevenLabs Music, exact length | none |
| lip-sync | Volcengine lite / lite / basic | PixVerse / Sync Lipsync 2 / Sync Lipsync 2 Pro, billed per second of the line | none (MCP only) |
| avatar | InfiniteTalk / Kling Avatar Standard / Pro | Pruna P-Video 2 Pro Avatar / Kling Avatar v2 std / Kling Avatar v2 pro, billed per second | none |

On Replicate and Higgsfield, video is billed per second: `generate.py clips --fit` asks for each shot's own length plus a little spare instead of 8s (cheaper; the trade-off is that lengthening a shot later can mean a paid remake). On Kie, Veo costs the same for any length, so `--fit` saves nothing (it says so). Neither Replicate nor Higgsfield shows a balance through its API, so `check_setup.py` only confirms the key works.

Every Kie job has a price: voiceover $0.07 per 1,000 characters, music $0.06 per Suno run (2 takes), lip-sync $0.04 per second of the line, avatars per second of talking ($0.06 draft, $0.04 standard, $0.08 best); the real cost (Kie's credits) is logged after the run. On Kie the draft avatar (InfiniteTalk) takes at most 15s of audio, standard and best (Kling) at most 5 minutes: a longer voiceover stops before anything is sent, so use `--quality standard` or split it. "Cost unknown" shows for Higgsfield's best image and video tiers, for an ElevenLabs key of the user's own (billed in the plan's characters, not dollars) and for pinned models with no price table: say so before the run; the cost is logged after it when the provider reports one.

**Higgsfield MCP** (`--set <slot>=mcp:higgsfield`). `generate.py` exits with code 3 and prints the prompt and settings; you run the job with the Higgsfield tools and save the file to the path it printed:
1. Once per conversation: `mcp__higgsfield__get_preferences` (and `balance` to show their credits).
2. Upload each local file it lists (start frame, references, clip, voiceover): `media_upload` with the filename and content type, a `curl -X PUT --upload-file` to the returned upload URL (must answer 200), then `media_confirm` per media type. A finished Higgsfield job can be passed on by its job id instead. `medias` values are always media or job ids, never URLs.
3. Price it first with the single tool and `get_cost: true` (e.g. `generate_video` with `{model, prompt, aspect_ratio: "9:16", duration, medias, get_cost: true}`). The model is the one for the `quality` it printed (tiers below), or the `model` it printed if there is one; `duration` is the `length` it printed, a whole number of seconds (already rounded up). With `--fit` it also prints `at least`: if the model only allows some durations, use the shortest allowed one that is at least that, never shorter (a clip shorter than its shot freezes in the edit). Quote the credits it returns and wait for a yes. It's priced in credits, not dollars: say so. If the tool answers with `unlim_choice` instead of a price, put that question to the user and call again with their answer as `use_unlim`. `image --n 3` hands over 3 file names: save one take as each.
4. Submit with the batch tool (`generate_image_batch`, `generate_video_batch`, `generate_audio_batch`, even for one job), then `jobs_wait` (up to 12 jobs, 15s per call) until every job is done. Never resubmit after a timeout: keep the job ids and wait on them, or it is paid twice. Apply any `adjustments` the server returns; if one changed the duration, check it is still at least the printed length.
5. Save each result with `curl -L --fail -o <path it printed> <result url>`; mute a clip that must be silent (`ffmpeg -i in.mp4 -c:v copy -an out.mp4`).
Models by tier: images `nano_banana` / `nano_banana_2` / `nano_banana_pro` (role `image_references`); video `veo3_1_lite` / `veo3_1` (variant `veo-3-1-fast`) / `kling3_0` (mode `pro`, `sound: "off"`), start frame as role `start_image`; voiceover `seed_audio`, or `text2speech_v2` with `variant: "elevenlabs"` for an ElevenLabs voice, with a voice from `list_voices` (`voice_type` + `voice_id`, `format: "mp3"`; `models_explore(type: "audio")` shows each model's settings); lip-sync `sync_so` (roles `input_video` + `input_audio`, `sync_mode: "bounce"`); avatar: make a clip of the photo first, then lip-sync it with `sync_so`. No music.

---

## Stage 0 — Start

- If the working folder has a project with `state.json`, offer to pick up where it stopped.
- Otherwise, **welcome them first** (before Setup): one short paragraph saying what you'll make together and how it works: "We'll go from your script to a finished ad in 10 steps. I'll explain each one as we go, you approve every step, and nothing that costs money runs without your yes." Then list the 10 step names on one line, and start Step 1.
- **If the message already holds a brief, read it first** and skip every question below that it (or `house-rules.md`) answers: brief or questions, start anywhere, where the clips come from (a brief from `brief-template.md` with the Clips line blank means AI), the hands-on level and budget, the look (Step 2), the hooks (Step 5). Confirm those answers in the brief summary table instead.
- **How hands-on, and the budget?** If `house-rules.md` doesn't say, ask once, as one question with buttons, and save the answer there:
  - **Approve every step (Recommended for a first ad).** Every gate in this file.
  - **Key steps only.** Approve the brief, the shot plan and hooks, and the final ad. Frames and clips are made without stopping, inside a budget they set now.
  - **Autopilot.** Make the whole ad inside a budget they set now. Stop only if something fails, the budget would be passed, or a choice can't be made from the brief.
  In library mode skip the budget part: nothing is generated (only an optional voiceover).
- **In key steps and autopilot**, the choices that are gates in every-step mode are made like this, and named in the brief summary so the user can change them: only one character sheet is made (option A), unless the brief or house rules name a look to follow; the voice is the first that fits the buyer (age, gender, accent); music follows house rules, else it is asked once inside the brief summary; test frames and clips are skipped (Rule 4).
- **The budget.** An approved budget counts as the yes for every paid run inside it (`generate.py --yes`). Once the project folder exists, save it from inside it: `python3 $S/check_setup.py --budget <usd>` (`--budget 0` removes it). From then on every estimate prints `This ad: $X spent + $Y now = $Z of your $B budget`, a run that would pass it is `BLOCKED` (ask the user before raising it), and every paid run ends with `Spent on this ad so far: $X of your $B budget`: show that as the running total at each step. `python3 $S/generate.py spend .` prints the total per slot at any time. `check_setup.py --limit <usd>` is a separate per-run safety net for every ad.
- **Where do the clips come from?** Ask with buttons (skip if `house-rules.md` or the brief says): **AI-generated** / **My own clip library** / **Mixed: my library first, AI for the gaps**. For library or mixed, ask for the folder (a local folder, or a cloud folder they download or connect), then run the Library steps below before Step 5. In library mode tell them the steps they'll see: Setup · Brief · Voiceover · Timing · Pick the clips · Edit · Checks and delivery (Step N of 7).
- **Start anywhere.** Ask with buttons what they already have, and start at that step: just a script (Step 2) / a script and voiceover (Step 2, voiceover option 1) / their own shot plan (Step 5: check it, then go on) / their own frames or clips (Step 8 or 9: drop them in `frames/` or `clips/` named by shot id) / a project from before (pick up from `state.json`).
- Then ask with buttons: "Paste your brief" (show the template from `brief-template.md`) or "Ask me the questions" (one question at a time, look first).

**Project folder:** `<brand>-<ad name>/` in the working directory, with every folder below made up front. Run the scripts from inside it (see `$S` above):

```
brief.md  state.json  shots.json  words.json  changes.md  budget.json
inputs/  audio/  characters/  frames/  clips/  manual/  qc/  final/
```

`budget.json` is written by `check_setup.py --budget`. A `<file>.job.json` next to an output is a paid job not collected yet: leave it.

Brand files, in the working directory next to the projects: `brands/<brand>/kit.md` (product, buyer, logo, look, avoid list) and `brands/<brand>/learnings.md` (feedback that applies to every ad for that brand). Read both at the start of every ad for that brand.

Update `state.json` at the end of every stage: `{"stage": "<name>", "done": [...], "waiting_on": "<what the user needs to do>"}`.

---

## Stage 1 — Brief and look (Step 2 of 10)

**The look comes first, before anything else in the brief.** If the brief names the look, write the look description from it and confirm it in the summary table instead of asking. Otherwise ask with buttons: "What should this ad look like?" Options: 3D animated (like an animated feature film) · Photoreal (looks filmed on a phone) · Motion graphics / 2D · Something else (describe it or send a reference). Then write one **look description** in 2 or 3 plain sentences, show it, and get a yes. It's reused word for word in every image and clip prompt, so every shot matches. For photoreal, also read `guides/phone-look-guide.md`.

1. **Check the must-haves:** script, product name, what it is, what it does, product photos, buyer (age, gender, country), their problem, voiceover option. If one is missing, ask for that one only. Never start without all of them. A brand kit that already exists fills the brand fields.
2. **Fill the optional fields with defaults** (the defaults are in `brief-template.md`).
3. **Reference ad:** if one is given, watch it (download, pull frames every second with ffmpeg, transcribe it) and write down its pace (seconds per shot), shot types, caption style and how it opens. Use that as the guide.
4. **Their day:** if the user gave no real moments from the buyer's life, suggest 4 or 5 specific ones (who they're with, what the problem costs them) and let them pick.
5. **Show one summary table:** field, what will be used, "you" or "default" (in key steps and autopilot, also the character, voice and music rules from Stage 0, and the budget). One approval covers it all.
6. Save `brief.md`. Save the brand fields to `brands/<brand>/kit.md`.

⛔ **Gate:** the user approves the brief.

---

## Stage 2 — Voiceover (Step 3 of 10)

Use the option from the brief. If it's missing, ask with buttons.

**1. I have the voiceover.** Copy it to `inputs/vo.mp3` (or `.wav`). Show its length (m:ss).

**2. Generate it.**
- Voice slot. List voices with `python3 $S/generate.py voices` and pick 3 that fit the buyer (age, gender, accent). Offer them with buttons, one line each. On Kie the voices are a fixed list of ElevenLabs v3 voices, and on Replicate a fixed list of 26 named ElevenLabs voices; a user who wants their own ElevenLabs voices sets `check_setup.py --set voice=api:elevenlabs` with an ElevenLabs key. On the Higgsfield MCP, list voices with `mcp__higgsfield__list_voices`.
- Save the script as plain text (`inputs/script.txt`) and make one take:
  `python3 $S/generate.py voice --text-file inputs/script.txt --out audio/vo.mp3 --voice <id>` (estimate, then `--yes`). For a script that isn't in English, add `--language <code>` (e.g. `fr`): Replicate's voices otherwise assume English. Use the same code for the timing (Stage 3) and as `"language"` in the shots file.
- Show the length. The user listens and approves, or asks for another voice.
- Save the chosen voice: `check_setup.py --voice-id <id>`, so hooks and later ads match.

**3. Talking characters** (people on screen say the lines). Ask with buttons:
- **Same voice all the way through (Recommended):** generate the voiceover first (option 2). Later, each talking shot is made as a normal clip of the person facing the camera, then lip-synced to its part of the voiceover (Stage 7). Exact words, one voice.
- **The video tool makes the voice:** cheaper and faster. Warn the user: the voice can change from clip to clip, and the tool sometimes changes words. Every talking clip is transcribed and any changed word is flagged (Stage 7), and `verify_vo.py` checks each line again in the final. There is no voiceover file: the shots file has no `"vo"`, each talking shot sets `"use_clip_audio": true` and holds its exact spoken line (the approved script) in `"text"`, and shot lengths come from the lines (about 2.7 spoken words a second). `edit.py` builds the sound from the clips and transcribes it into `words.json` (for the captions, and every time even with captions off), and does it again by itself when a talking clip is remade, moved or trimmed.

**4. AI talking avatar.** One AI presenter talks to camera for the whole ad, and the avatar video is the voiceover and the main picture. If the user already made the avatar video (in HeyGen or similar), copy it to `inputs/avatar.mp4`. Its sound is the voiceover: set `"vo": "inputs/avatar.mp4"` in the shots file (`edit.py` and `verify_vo.py` also use an avatar shot's video as the voiceover by themselves when `"vo"` is missing), and time it like any voiceover (Stage 3). If they have a photo of the presenter (or you make one in Stage 5), make the talking video from the photo and the voiceover. Only the cut-aways are generated as clips:
`python3 $S/generate.py avatar --image inputs/host.png --audio audio/vo.mp3 --out inputs/avatar.mp4 --prompt "<expression, movement, camera>"`

**5. No voiceover (text on screen).** The story is told in on-screen text over music. Each line is one `"type": "text"` shot with its words in `"text"`; its time on screen = its words ÷ 3 per second, at least 1.5s. The card's background is a clip or image (`"source"`) or a plain colour (`"bg": "#1a1a1a"`). The shots file has no `"vo"`.

⛔ **Gate:** the user approves the voiceover (options 1, 2, 3 and 4).

---

## Stage 3 — Timing (Step 4 of 10)

- **Options 1, 2, 4 and the same-voice route of 3:** `python3 $S/transcribe.py <vo or avatar file> <project> --script inputs/script.txt`. This writes `words.json` (every word with its time) and `shots_draft.json` (one draft shot per idea, none longer than the video slot's `max_seconds`). The times come from Whisper; the words come from the script: words that line up one for one are fixed automatically. An existing `words.json` is kept as `words.json.bak`.
- **A voiceover generated from the script** (option 2, the same-voice route of 3, and option 4 when the avatar was made from the script): add `--trust-script`. Every word it can't line up takes the script's spelling, spread over the time Whisper heard something there, and each change is printed, so nothing is left to fix by hand.
- **Their own recording** (option 1, or an avatar video made elsewhere): leave `--trust-script` off, since the take may really differ from the script. Fix every line it prints as `CHECK BY HAND` in `words.json` before Step 5: change the word's `"w"` and keep its `"heard"` (what Whisper heard, which `verify_vo.py` compares against); add a missing word with `"heard": ""`; delete a word the voiceover doesn't say; delete `"heard"` from a word it really says that way. It always ends with `Every word follows the script.` or `N word(s) are still as Whisper heard them`: don't go on until it's the first, or the user has heard and accepted each one. Words left as heard would end up in the captions, so `edit.py` stops the final export until they're fixed (a `--preview` shows them; `--allow-unchecked` cuts the final anyway, only after the user has heard and accepted them).
- **Not in English:** add `--language <code>` (e.g. `fr`), the same code as the voiceover. It uses the multilingual speech model instead of the English-only one. French punctuation with a space before it (`encore ?`, `Sommeil :`, `« »`) is fine: the mark stays on its word.
- **Less than half of the script heard:** it writes nothing and stops (`Only 20% of the script was heard...`). Usually the voiceover isn't in English and `--language` is missing; otherwise check that it's the right voiceover and the right script, then run it again.
- A pause of a second or more can become a draft shot of its own with empty `"text"`: give it a visual, or merge it into the shot next to it.
- **Option 5:** nothing to time. Each card's length comes from its words (Stage 2), and no `words.json` is needed.

---

## Library (UGC and mixed modes)

Runs once per library, then only for new clips. Free.

1. **Index:** `python3 $S/library.py index <folder>`. It reads every clip's length and shape and saves 4 frames from each into `<folder>/_index/`. Clips in subfolders are indexed too, named by their path (`2024/walk.mp4`: use that path in `"source"`). Re-run it when clips are added; it only processes new ones (and makes deleted frames again). Files it can't read (empty, still copying, no picture) are skipped and listed: tell the user, and index again once they're fixed. HDR or wide-colour phone clips (HLG/PQ) are flagged with a convert command each: they look flat in the ad unless converted. Convert them, move the originals out of the folder, and index again.
2. **Look and tag:** `python3 $S/library.py sheet <folder> --page N` makes one image of 12 clips × 4 frames. Look at every page and describe each clip in plain words: who is in it (age, gender), what they do, where, the mood, and whether the product shows. File names often describe the clip; still check the frames. Note which of the 4 frames is the best moment, so you can set `in`. Write one `<clip><TAB><tags>` line per clip to a `tags.tsv` and save them all at once: `python3 $S/library.py tag <folder> --file tags.tsv`. If a line is wrong, nothing is saved and the problems are listed: fix them and run it again.
3. **Licence check (once):** ask whether the clips are cleared for use in ads. If they aren't sure, say so in the final README.
4. **Fit check (before planning, every ad):** read `python3 $S/library.py list <folder>` (one line per clip: length, shape, HDR, how often used, tags; `--untagged`, `--unused`) next to the script and estimate how many lines have a clip that really shows them (the right kind of person, the right action or place). If it's under half, say so plainly before the shot plan, with the reason in one line (what the clips show vs what the script is about), and ask with buttons, with no recommendation (one option costs money, the others don't): **Switch to mixed: the lines with no good clip are made with AI, about $X** (lines × the clip price, plus a frame each, from `generate.py prices`) / **Library only: free, using the closest clips, marked in the plan** / **Add clips to the library first**. In mixed mode the same check tells the user up front how many AI shots and roughly what they'll cost.
5. **Repeats:** each earlier ad a clip was used in costs it a point in `library.py find`, and `--avoid-used` leaves used clips out. Ask once whether to avoid clips used in recent ads. After the final, mark every clip in the ad in one call: `python3 $S/library.py used <folder> <clip> <clip>...` (the project defaults to the working folder's name; `--project <name>` sets it). Running it again in a revision doesn't count them twice.

## Stage 4 — Shot plan and hooks (Step 5 of 10)

### Before I plan the shots

One quick round, one question at a time with buttons. These are creative choices, so no option is marked as recommended; each has a default (listed first) that's used if the user says "use the defaults" at any point.

**Only ask what fits this ad.** The list below is a menu, not a script. Read the script, product and look first, then pick the questions that change the shots for *this* ad, and word them in its world (its niche, its character, its product). Skip anything the brief already answered and anything that doesn't apply: no ingredient question when the script names no ingredients, no "who is the main character" for a faceless motion-graphics ad, no "how time passes" without a timeline. Usually 3 to 5 questions, never all 9 by default. Add a question that isn't on the list if this ad needs it.

1. **Who is the main character?** Age, job, life (if the brief didn't say).
2. **Real moments from their day.** Where the problem hits hardest, and who's there. Suggest 4 or 5 and let them pick.
3. **Who's in their life?** Partner, kids, friends, colleagues: shots with other people land harder.
4. **Tone of the low point.** Funny and relatable, or serious.
5. **How the explanation or ingredient lines look.** Simple animation inside the body / a visual metaphor / lifestyle only.
6. **How the product appears.** Only the product itself early, with branded packaging near the end / packaging from the start.
7. **How time passes** (for "week 1, week 2" scripts). On-screen labels, or only through the voiceover and how they look.
8. **Pace.** A cut every 2 to 3 seconds / one shot per line. Show the number of clips and the cost next to each.
9. **Rough cost.** Number of clips × the clip price, plus images. Offer stills with a slow zoom for some shots if they want it cheaper.

The prices for 8 and 9 come from `python3 $S/generate.py prices` (free, makes nothing): for each tier of every slot, the price per image, per clip at 4/6/8s (or one price for any length, on Kie), with sound for talking shots, per 1,000 characters, per 60s track, and per 10s of lip-sync or avatar; it marks the default. `--provider <name>` shows another provider's to compare. `python3 $S/generate.py clips . --shots shots_draft.json [--fit]` prices the draft's own clips (a draft can only be priced, never run): multiply for each pace option. "Cost unknown" means the provider publishes no price: say so.

### The shot plan

Start from `shots_draft.json`. Show one table:

| Shot | Time | Line | What we see | Type | Source |
|---|---|---|---|---|---|

**Source** is `AI` or `Library: <clip> @ <in seconds>`. In library and mixed mode, fill it like this for every line:
1. Pick from the `library.py list <folder>` you read for the fit check, and look at the frames of the candidates. `python3 $S/library.py find <folder> "<the line, or what we should see>" [--avoid-used]` ranks clips by their names and tags: use it to double-check a pick.
2. **Good match** (shows what the line says, the right kind of person, no clash with the shots around it): use it, with `in` set to the best moment. The shot is `"type": "library"`, `"source": "<folder>/<clip>"`.
3. **No good match:** library mode: use the closest clip and mark the row `closest match` so the user sees it. Above the table, give the count ("9 of 22 lines have a good clip; the other 13 use the closest one"). Mixed mode: mark the row `AI` with its cost, and add it to the list of shots Steps 6 to 8 will make.
4. The user can flip any row ("use AI for s05", "find a library clip for s09").
5. Library rules: don't use the same clip twice in a row; don't reuse the same moment of a clip; keep one main person where the story has one main character; vertical clips are best (horizontal ones are cropped to the middle, so check the person stays in frame).

**Types:** `clip` (generated from a start frame), `talking` (clip + voice, option 3), `image` (a still with a slow push-in: product photo, end card), `avatar` (the AI talking-avatar video from option 4), `text` (a text card, option 5).

**Self-check before showing it:**
- Every shot shows what its line says, clearly enough that someone watching on mute follows the story from the pictures and captions.
- One timeline, in order: the past first, then forward. No jumping back and forth.
- No camera angle twice in a row. Vary: wide, overhead on the hands, front close-up, profile, over the shoulder, low angle, extreme close-up.
- Real moments from this buyer's life, ideally with other people (the partner who notices, the friend, the grandchild). Not stock moments like typing on a laptop or writing a list. Ask: would someone with this problem think "that's literally me"?
- Close-ups on the big emotional moments (the low point, the relief, the win).
- Early product shots show only the product itself (a capsule in a palm); branded packaging comes near the end or when the brand is named.
- Screens face the character, not the viewer. Show what's on a screen only over the shoulder or in a hand-and-phone close-up.
- Meta-safe.
- The explanation lines are shown the way the brief chose (simple 3D animation, a visual metaphor, or lifestyle only).

### The hooks

The user controls the hooks. If the brief settled them, use that. Otherwise ask with buttons: **"How do you want to handle hooks?"**

| Option | What happens |
|---|---|
| I'll write my own hook lines | The user pastes 1 or more opening lines |
| Same opening line, different visuals | The user describes each visual, or picks from suggestions |
| Suggest some for me | 3 to 5 hook lines or visuals, each with its angle (emotion, curiosity, visual metaphor). The user keeps, edits or deletes each one |
| Just 1 hook | The script's first line |

Each hook gets a card:
- **Hook line** (spoken or on-screen text)
- **What we see**, shot by shot, for the first 3 to 5 seconds
- **Join:** how it flows into the main ad's next line with no jump. Read the hook line followed by line 2 out loud in your head; if it doesn't follow, fix the hook, never line 2.

Save `shots.json`.

⛔ **Gate:** the user approves the shot plan and every hook card. This is the most important gate. Changes here are free.

**Then build each hook's plan with `hook.py`** (hook B, C...; A is the main ad), from inside the project:
1. **A new hook line:** write it to `inputs/hook_<letter>.txt` and make its take with the saved voice: `python3 $S/generate.py voice --text-file inputs/hook_<letter>.txt --out audio/hook<letter>_line.mp3` (estimate, then `--yes`; add `--language <code>` if it isn't English). Their own recording of the line works too.
2. `python3 $S/hook.py . <letter> --line-audio audio/hook<letter>_line.mp3 [--from sNN] [--trust-script]`. Pass `--trust-script` when the main voiceover was timed with it (both generated from the script). The language comes from `"language"` in `shots.json`.
   - It never changes `audio/vo.mp3`. It writes `audio/vo_hook<letter>.mp3` (the hook line, then the main voiceover from the silence before the first kept word, level-matched), `inputs/script_hook<letter>.txt`, `words_hook<letter>.json` (it runs `transcribe.py` itself) and `shots_hook<letter>.json`.
   - `shots_hook<letter>.json` starts with a placeholder shot `h<letter>01` (0 to the first kept shot), then every kept shot moved by the same amount, ids unchanged so their clips are reused. Music `switch_at` moves with them; captions, end card, platform and language are copied.
   - `--from` is the first main shot the hook keeps; by default it's the shot where line 2 starts.
   - It prints how far the shots moved, any `WARNING` at the join and the next step. On a warning, look up that word in `words.json`: if the main voiceover was heard the same way there (its `"heard"`, often a brand name), the join is fine. Otherwise ask the user to listen to `audio/vo_hook<letter>.mp3` at that time; if a word is clipped, pick a `--from` shot that starts after a pause and run it again with `--force`. If it says words were left as heard, fix them in `words_hook<letter>.json` as in Step 4 (or re-run with `--trust-script --force` when both takes were generated from the script).
3. **Same line, new visuals:** `python3 $S/hook.py . <letter> [--from sNN]`, with no `--line-audio`: the same voiceover, a new opening picture.
4. **Fill `h<letter>01`:** its `visual`, `video_prompt` and `frame` (`frames/h<letter>01.png`, made in Step 7 with the others), a library `source`, or the hook line on a text card in a text-only ad. Split it into `h<letter>01`, `h<letter>02`... for more shots (they must still touch end to end). A new hook shot always gets its own id: with a main-ad id, `generate.py clips` skips it as already made and the hook plays the main ad's clip.
5. Running it again needs `--force`: the hook shots already filled are kept and re-timed, and the old file is kept as `.bak`.
6. **Talking characters with no voiceover:** there is nothing to join, so `hook.py` stops and prints the by-hand plan (a talking shot `h<letter>01` first, every later shot moved by its length, its own `"words"` file, which `edit.py` fills from the clips).

Any part of any hook can be changed without touching the rest. Adding a hook later is a new card and a `hook.py` run; the main ad is not rebuilt.

---

## Stage 5 — Characters (Step 6 of 10)

**Library mode: skip this step.** **Mixed mode:** make sheets only for people in the AI rows, and when that person is someone from the library footage, make the sheet from their best library frame (`--ref <folder>/_index/frames/<frame>.jpg`, "the same person as the attached photo") so the AI shots match. **Also skip this step** when no person appears in more than one shot (motion graphics, text-only, product-only ads). Say so in one line and go to Step 7.

1. Use the **look description** approved in Step 2 word for word in every sheet prompt.
2. Offer **3 different people** who all fit the buyer: vary ethnicity, hair, age within the range, outfit. Never 3 takes of the same person. One character sheet each, written to one jobs file so the user sees one cost and approves once:
   `python3 $S/generate.py images <project>/characters_jobs.json` with `[{"prompt": "<sheet prompt A>", "out": "characters/option_a.png", "aspect": "16:9"}, ...]`. Keep jobs files in the project folder: the paths inside are read from the jobs file's own folder.
   Sheet prompt: "<look> character sheet. One person shown 4 times on a plain light-grey background: face close-up, full body front, full body three-quarter left, full body three-quarter right. Neutral expression. <age, face, skin, hair, build, outfit, small details>. Same person in all 4 views. No text, no logos."
3. The user picks one. That sheet becomes `characters/master.png`.
4. **Every other version of that person** (struggling, recovered, younger) is an **edit of the master**, never a new prompt:
   `--ref characters/master.png --prompt "Edit the attached sheet. Keep the face, features and proportions identical. Change only <what changes>."`
5. A user's own photo of the presenter or character replaces the sheet.
6. Other people who appear more than once (partner, friend) get their own sheet the same way.

⛔ **Gate:** the user picks the main character and approves every other sheet. (In key steps and autopilot, one sheet is made and used, following the brief or house rules if they name a look: see Stage 0.)

---

## Stage 6 — Start frames (Step 7 of 10)

One frame per `clip` and `talking` shot (library mode: skip this step; mixed mode: the AI rows only, in the look of the library footage, which is usually the photoreal phone look in `guides/phone-look-guide.md`).

- Attach **exactly one** character sheet per frame (two sheets blend the faces): `--ref characters/<stage>.png`. Add a place reference if there is one. Prompts say "exactly as the attached sheet" and never describe the face again.
- Reuse the first approved frame of a place as the reference for later shots there.
- **Product shots:** the character using the product (holding it, taking it). Attach the master sheet, an approved frame of them, and a clean product photo. Spell out the big label text. Use `--quality best` for these. Check the brand name is spelled right.
- **4:5 safe zone:** every face, product and key prop sits between 15% and 85% of the frame height. Write it into every prompt: "full-bleed vertical image that fills the whole frame edge to edge, no borders, no bands, no letterbox; the faces and hands are in the middle of the frame, with the scene continuing above and below them". Never write "the top and bottom are background only": image models read it as empty bands. **1:1 is tighter:** when the brief wants 1:1, the square keeps only the middle 22% to 78% of the height, so write that zone into the prompts instead. Check every frame for bands before showing the grid. `generate.py image` and `images` also check each tall frame by themselves: one that looks letterboxed is remade once on the best model (the first take is kept as `<name>_banded.png`). The estimate prints that remake's price on its own line ("not in the total", or "cost unknown" on Higgsfield): say so when you quote it. If the remakes could take the run over the per-run limit or the ad's budget, they're off for that run. A frame that still looks off, wasn't remade, or whose remake failed (the first take stays in place) gets a CHECK line. No remake with `--quality best` or a set model.
- **Talking shots:** the person faces the camera, mouth closed and about to speak, front or slightly to one side, no hands in front of the face.
- One clear action per frame. Describe camera position, the action and the light.

Make the first frame as a test (`generate.py image`). After a yes, put the rest in one jobs file and make them in one run with one cost: `python3 $S/generate.py images <project>/frames_jobs.json` (each job: `prompt`, `out`, `refs`, optional `quality`; keep the jobs file in the project folder). In key steps and autopilot there is no test frame: make them all in one run and report only the ones that fail the self-check. `images` skips frames that already exist, so a jobs file can be run again safely; `--only s03 s07` remakes the named ones and `--redo` remakes them all. Every remake (with `image` too) keeps the old take as `<name>_prev.png`. Show all frames in one grid image (ffmpeg tile) with shot ids.

**Self-check before showing the grid:** 4:5 safe zone, no angle repeated back to back, enough close-ups on the emotional moments, the person's state matches the line (tired vs rested, messy room vs tidy), no strange props, hands and product held in a way that makes physical sense.

⛔ **Gate:** the user approves the frames.

---

## Stage 7 — Clips (Step 8 of 10)

Library mode: skip this step. Mixed mode: the AI rows only.

1. Write each clip's `video_prompt` in `shots.json`: the camera, the movement, one action, the light, in plain words. For `talking` shots made by the video tool, put the exact line in quotes: `she looks at the camera and says: "<line>"`.
2. Run `python3 $S/generate.py clips <project>` for the estimate. In every-step mode, make 1 or 2 test clips first (`--only s01 s02`), then the rest after a yes; in key steps and autopilot make them all in one run and report only the failures. It skips clips that already exist; `--only` remakes the named ones (clip and talking shots) and keeps a copy of the old take as `<id>_prev.mp4`. The old take stays in place until the new one arrives, so a failed or blocked remake loses nothing. A talking shot that plays a lip-synced take (`"clip"`) needs `generate.py lipsync` run again after its clip is remade, or the edit keeps playing the old take: `generate.py` prints this before the estimate, so add the lip-sync price to the quote. On a provider that bills per second (Replicate, Higgsfield), offer `--fit` with both prices: each clip is its shot's length plus a little spare (a 3.1s shot is a 4s Veo clip) instead of 8s. The last clip is sized to the voiceover's end with the same rule as the edit (the avatar video counts when there's no `"vo"`). On Kie `--fit` saves nothing, and `generate.py` says so. Clips take minutes: run the command with a long Bash timeout or in the background; if it's killed, run it again and it collects the paid jobs.
3. **Check every clip yourself** before showing anything: `python3 $S/contact_sheet.py <project>` writes `qc/contact_sheet.jpg`, or `qc/contact_sheet_1.jpg`, `_2.jpg`... with more than 6 clips (a hook plan: `contact_sheet_shots_hook<letter>[_N].jpg`). Look at every page. Each frame keeps its clip's shape; the label shows the id, the plan times, the shot length and the clip length. Look for warped hands, the face changing, objects changing shape, text appearing, the wrong product. Then act on its `CHECK` lines:
   - a frozen start: set `"in": <seconds>` on that shot so the edit starts after it;
   - a clip too short for its shot (`the last 1.5s would freeze`): a smaller `in`, a shorter shot, a longer clip (remake it), or `"freeze_ok": true` on the shot if a held last frame is fine;
   - shots with no clip yet are listed with the command that makes them.
4. **Talking shots:**
   - **Same-voice route:** cut each talking shot's audio out of the voiceover from the shot's `start` to its `end` (not just its words: the lip-synced take is as long as its audio, and `edit.py` stops when a clip is more than 0.25s shorter than its shot): `ffmpeg -i audio/vo.mp3 -ss <start> -to <end> audio/<id>.mp3`. Then
     `python3 $S/generate.py lipsync --video clips/<id>.mp4 --audio audio/<id>.mp3 --out clips/<id>_talk.mp4`
     and point the shot at the lip-synced file with `"clip": "clips/<id>_talk.mp4"`, leaving `in` at 0 (the take starts at the shot's start). Use the part of the clip where the person faces the camera (cut it out first if they only turn to the camera partway through). A longer clip is trimmed to the audio, a shorter one plays back and forth. Replicate's Sync models move only a mouth that is already moving, so the clip should show the person talking (talking shots are made that way), not a still face.
   - **Video-tool-voice route:** transcribe every talking clip into its own words file, so the project's `words.json` and `shots_draft.json` are left alone: `python3 $S/transcribe.py clips/<id>.mp4 <project> --no-draft --words-out audio/<id>_words.json` (plus `--language <code>` if it isn't English). Compare it with its line. Any changed word is flagged to the user with the clip id; the user decides whether to remake it. (`verify_vo.py` checks every line again in the final, Stage 8.)
5. Show the user the contact sheet and the list of clips you suggest remaking, with the reason for each. Remake only on a yes.
6. On Kie, Veo sometimes refuses a clip with "unable to generate audio". `generate.py` retries by itself (without the no-audio line, then on the other Veo models that cost the same or less; refused tries aren't charged) and notes which model made it. If every try is refused, reword the prompt as below. Replicate and Higgsfield turn the sound off instead, so this doesn't come up there.
7. If a clip is blocked (usually a safety filter on a person + a medical detail), soften the prompt and say what you changed. If credit runs out, stop, say so, and offer to finish the edit with the start frames as stills for the missing shots.

⛔ **Gate:** the user approves the clips (or says they don't need to see them).

---

## Stage 8 — Edit (Step 9 of 10)

1. **Music (always ask, never default to none).** In key steps and autopilot, use the answer from house rules or the brief summary. Otherwise, before the first edit, ask with buttons, with no option marked as recommended (music is taste): "Music under the ad?" Attach a track / Two tracks, switching at a line / Make a backing track for this concept / No music. "Make a backing track" writes a short mood prompt from the concept and runs `generate.py music --prompt "..." --out inputs/music.mp3 --seconds <ad length + 2>`: on Kie, 2 instrumental takes with Suno and the user picks one; on Replicate, one instrumental take of exactly that length (estimate first). Otherwise it uses whatever music tool fills the music slot (Higgsfield has none); otherwise write a short music prompt (mood, tempo, instruments, "instrumental, no vocals") for them to run in any music app and drop the file into `inputs/`. Save the answer to house rules so the next ad asks only to confirm.
2. `python3 $S/edit.py <project> --preview` for a fast low-res check, then `python3 $S/edit.py <project>` for the full export.
3. What the edit does: cuts every clip to its exact slot, frame-accurate, at 1080x1920; the voiceover is the only voice (or, on the talking-characters route where the video tool makes the voice, the clips' own voices); music sits under it and dips automatically while someone speaks (`"duck": false` turns that off); captions from `words.json`; end card if picked.
   - **Before rendering anything it checks the whole plan** and stops with one line per problem, each naming its shot: the shots file isn't valid JSON (with its line) or has no shots; an id is missing or used twice; an unknown type; a missing file (voiceover, music, `file2`, image, background, video, end card); a voiceover, music track or `use_clip_audio` clip with no sound track (Replicate and Higgsfield make silent clips); a bad `in`, `speed`, `text_pos` or `caption_pos`; an unknown captions preset. It also stops when shots don't touch end to end, a shot is shorter than one frame, or a shot would start at or past the end of its clip (its `in`).
   - **A clip too short for its shot:** if the shot would hold the clip's last frame for more than 0.25s, it stops, naming the shot, the clip's length and the frozen seconds, with the fix (a smaller `in`, a shorter shot, or a remake: `generate.py clips . --only sNN`). `"freeze_ok": true` on the shot allows it; on the last shot, a hold after the last word is only a note.
   - **With a voiceover and captions on, it needs the words file:** without it, it stops and prints the `transcribe.py` command to run (or run `edit.py` with `--no-captions`).
   - **On the talking-characters route** with no voiceover it writes `words.json` from the clips' voices every time, captions or not (for the captions, and so `qc.py` can tell a closing hold after the last word; `verify_vo.py` checks each talking shot's `"text"` instead), plus `words.json.src` (which clips it heard): hand fixes in `words.json` stay while those clips stay the same, and a remade, moved or trimmed talking clip is transcribed again by itself. Delete `words.json` to force a new one.
   - **After `saved` it may print `Look at these before showing it:`.** Read every note and pass it on to the user before showing the ad. They cover: the words file doesn't match the voiceover's length, or is older than it (time it again with the printed command); the last shot runs on more than 1s past the plan with words spoken after it (add shots for the last lines); the last shot holds still after the last word; a talking shot has no clip yet, so its line is silent; captions heard from the clips' voices (proofread them in the preview); captions left off a card that fills the middle.
   - Fix whatever it names in the shots file (or the clip) and run it again.
4. **Captions** use the preset from the brief:
   - **Bold:** full capitals, 1 line, the current word highlighted; long words shrink to fit
   - **Clean:** the script's own capitals (not all caps), up to 2 lines, balanced
   - **None**
   - Never 3 lines. A caption ends at punctuation (French ` ?` and `»` too) or at a pause; longer stretches are split evenly, so captions don't end on a short word like "a" or "the" or leave one word alone when that can be helped.
   - Captions sit in the middle of the frame, and low (two-thirds down) on avatar and talking shots and any `use_clip_audio` shot, so they don't cover the mouth. Never at the top, always above the platform's bottom buttons, and never over a text card or on-screen text: `edit.py` moves them just below it (above if there's no room) and prints a line for each shot it moved, or leaves them off a shot whose card fills the middle. They stop at the end card.
5. **Then always** run `python3 $S/verify_vo.py <project>`. It checks the newest take of every final in `final/` (not previews or older `_v<n>` takes) against the plan it was cut from (a `_hookB_` file against `shots_hookB.json`). Never deliver a file that fails it.
   - **Voiceover route:** the final's sound against the voiceover, every word, and the captions' words file against this voiceover. It FAILS when that file isn't this voiceover's: out of sync (a words file from another take) or words the voiceover doesn't say (a retake with changed words, or a hook without its own words file). Re-run `transcribe.py` on that voiceover as printed (with `--words-out` for a hook), then `edit.py`.
   - **Talking-characters route:** each talking shot's own line (its `"text"`, the approved script) against what is heard inside that shot; `words.json` isn't used here. A line cut off by its slot, a clip saying something else, or a missing or silent clip FAILS, named by shot id. A single changed word is a note: tell the user and let them decide.
   - **No speech to check** (no voiceover, avatar or clip voice: text cards, plain image shots) passes. But a words file next to such a plan FAILS as cut without its voiceover: put the `"vo"` back, or delete the words file if the ad has no voice on purpose.
   - A problem with the plan, the words file or the voiceover is a FAIL line with its fix; the other files are still checked.
   - It also notes words still as Whisper heard them: fix them in the words file (Step 4), then run `edit.py` again.
6. `edit.py` saves `final/<brand>-<ad name>_hookA_9x16_v1.mp4`, with a new version number for every change.

⛔ **Gate:** the user reviews the final.

---

## The shots file

`shots.json` (and one `shots_hook<letter>.json` per extra hook) is the plan every script reads:

```json
{
  "vo": "audio/vo.mp3",
  "words": "words.json",
  "quality": "standard",
  "shots": [
    {"id": "s01", "start": 0.0, "end": 2.4, "type": "clip", "text": "<the line>", "visual": "<what we see>",
     "frame": "frames/s01.png", "video_prompt": "..."},
    {"id": "s02", "start": 2.4, "end": 4.8, "type": "talking", "clip": "clips/s02_talk.mp4"},
    {"id": "s03", "start": 4.8, "end": 7.0, "type": "image", "source": "inputs/product.jpg", "caption_pos": "low"},
    {"id": "s04", "start": 7.0, "end": 9.0, "type": "avatar", "source": "inputs/avatar.mp4"},
    {"id": "s05", "start": 9.0, "end": 11.0, "type": "text", "text": "<on-screen words>", "bg": "#1a1a1a"}
  ],
  "music": {"file": "inputs/music.mp3", "volume": 0.12},
  "endcard": {"image": "frames/endcard.png", "seconds": 3},
  "captions": {"preset": "bold"}
}
```

- Shots touch end to end, in time order: the first starts at 0 and each `start` = the previous `end`. `edit.py` stops and names the shot if not. The last shot runs to the end of the voiceover by itself (`edit.py` notes it when that's more than 1s with words spoken after the plan's end: add shots for those lines).
- `words`: the word timings the captions are cut from. Always set it in a hook file (`hook.py` does). A `shots_hook<letter>.json` without it uses `words_hook<letter>.json` when that file exists or the hook has its own `vo`, and asks you to add the key.
- `in`: where to start inside the clip (skips a frozen start). For `avatar` it defaults to the shot's `start`, so the avatar stays in sync. Lip-synced talking clips start at the shot's start, so leave `in` at 0 on them.
- `clip`: use a different file than `clips/<id>.mp4` (a lip-synced take).
- `freeze_ok`: `true` lets the shot hold its clip's last frame (or stand still) on purpose. Without it, `edit.py` stops on a clip more than 0.25s too short for its shot, and `qc.py` and `contact_sheet.py` flag a still clip.
- `"type": "library"` with `"source": "<library folder>/<clip>"` plays a clip from the user's library from `in` seconds (default 0). Its own sound is muted unless `use_clip_audio` is set. Horizontal clips are cropped to the middle of the frame.
- `on_screen`: extra words shown on any shot (an offer, a label). `text_pos` moves them and `caption_pos` the captions (`"middle"`, `"low"` or a fraction of the height, 0.5 = middle); captions are still moved off a card or on-screen text. For a 1:1 version keep `text_pos` from 0.25 to 0.75 and `caption_pos` at most 0.75 (`"low"` is fine): the square cuts off the rest. `{ }` and a backslash in `on_screen` or `text` show as `( )` and `/`.
- `use_clip_audio`: keep the clip's own sound (the video tool's voice). On such a shot, `"text"` is the exact spoken line: `verify_vo.py` checks the final against it.
- `quality` per shot or for the whole file: `draft`, `standard` (default) or `best`.
- `language`: the voiceover's language code (e.g. `"fr"`) when it isn't English. `verify_vo.py` and `qc.py` use it to hear the words.
- `platform`: `"meta"`, `"tiktok"` or `"youtube"`, from the brief. `qc.py` checks that platform's length and file-size limits (meta if it's missing).
- A shot with no clip yet plays its start frame as a still, so an edit can always be made.
- `captions`: `{"preset": "bold"}`, `{"preset": "clean"}`, `{"preset": "none"}` or `false` (`"captions": "clean"` works too). Extra keys override the preset: `size`, `font`, `font_file`, `colour`, `highlight`, `max_words` (the most words per caption), and `position` for every shot (`"middle"`, `"low"` or a fraction of the height from 0.35 to 0.8; a shot's own `caption_pos` wins).
- `music.volume` 0.08 to 0.15 sits under a voice; text-only ads can go up to 0.3. The music dips under speech by itself; `"duck": false` keeps it level. `"music": "inputs/music.mp3"` is short for `{"file": ...}` at the default volume.
- **Two music tracks:** `"music": {"file": "inputs/song1.mp3", "file2": "inputs/song2.mp3", "switch_at": 31.2}` switches tracks at that second (pick the second from `words.json`). `volume2` sets the second track's level.

---

## Stage 9 — Variants (Step 10 of 10)

From the brief:

- **Hooks:** each hook's plan comes from `hook.py` (Step 5; run it now if it wasn't). `python3 $S/generate.py clips <project> --shots shots_hookB.json` makes only that hook's new clips (its `hB01` frame is made in Step 7), then `python3 $S/edit.py <project> --shots shots_hookB.json` cuts that version, then `verify_vo.py`.
- **Sizes:** `python3 $S/variants.py <project> --sizes 4x5 1x1 16x9`. 4x5 keeps 15% to 85% of the height, so the 4:5 safe zone keeps faces and products in it. 1x1 is a centre crop that keeps only the middle 22% to 78%: look at every 1x1 file for cut-off faces, products, captions or text (`variants.py` reminds you). It makes sizes only of the newest `_v<n>` take of each 9:16 and names the older takes it skipped (`--files final/<file>.mp4` makes sizes of one of those). A size already made from the same 9:16 is kept (`--redo` makes it again); one whose 9:16 was cut again under the same name is made again by itself. A 9:16 that is cut off, a preview or unreadable is named with what to do, the other files are still made, and it exits 1.
- **Shorter cuts (15s, 30s):** suggest which lines to keep and show the shorter script; cut only after a yes. Shorter cuts need a voiceover recorded for that length (or option 5); the voiceover is never cut mid-sentence.

Run `python3 $S/verify_vo.py <project>` again: it checks every hook and size in `final/`, each against its own plan.

---

## Stage 10 — Checks and delivery (end of Step 10)

1. `python3 $S/qc.py <project> --platform <meta|tiktok|youtube>` (the brief's platform; it can be left out when the shots file has `"platform"`) runs every check on the newest take of every file in `final/` (not previews or older `_v<n>` takes): size and shape, H.264 and AAC, sound and picture both run the full length, no black picture (a dark text card is only noted: look at a frame of it), length and file size for the platform, and the voiceover check on 9:16 files whose ad speaks (a voiceover, an avatar or clip voices).
   - **Frozen picture** (9:16 files): a clip, talking, library or avatar shot whose picture stands still for 1s or more FAILS, naming the shot and the cause: the clip runs out before the shot ends, it starts frozen (with the `"in"` to set), the whole shot is still, or it stops mid-shot. Fix it and run `edit.py` again, or set `"freeze_ok": true` if it's on purpose. Stills, text cards and the end card may hold still; a shot with `freeze_ok`, or the last shot holding after the last word, is only a note.
   - **Sizes from an old cut:** a 4x5, 1x1 or 16x9 file made from an older 9:16 take, or before the 9:16 was cut again, FAILS: run `variants.py` again.
   - It notes clip shots that have no clip yet (their start frame plays as a still).
   - It does not check captions: look at a few frames yourself to make sure no caption covers a face or sits under the app's buttons.
2. Fix anything that fails before sending.
3. Write `final/README.md`: every file made, which tools made it, the cost (`generate.py spend .` gives the total per slot; say how many jobs had no known cost), and anything missing or replaced with a still.
4. Send the finals to the user. If a Drive or Dropbox tool is connected and the user wants it, upload them there.

---

## Revisions (working with the user as their editor)

The user watches the draft and gives notes like they would to an editor. This step is a loop: draft → notes → plan → v2 → notes, until they're happy.

**1. Every draft goes out with a shot map.** After each edit run `python3 $S/shot_map.py <project> final/<draft>.mp4` (a hook draft uses its own `shots_hook<letter>.json` by itself). It makes one image of every shot with its start-end time, id and line (`final/<draft>_shotmap.jpg`). The times match the draft: a last shot that runs on to the voiceover's end shows its real end (with `(runs on to the voiceover's end, Xs more)` when that's more than 1s), and the end card has its own picture. Send the draft and the shot map together, and say: "Give notes any way you like: a time (0:23), a line ('when she says carpet'), or a description ('the bathroom bit')."

**2. Turn every note into a shot.** Match times to shots with the shots file, lines with `words.json`, and descriptions with the shot map. If a note could mean two shots, ask which, with the two thumbnails.

**3. Sort the notes into free and paid, and show the plan before changing anything:**

| Free (edit only, instant) | Paid (makes something new) |
|---|---|
| Swap a shot for another existing clip or frame | A new clip or frame |
| Trim, extend, move or reorder shots | A new character look |
| Skip a frozen or bad start (`in`) | A new voiceover or hook line |
| Caption size, position (captions lower = `captions.position`), style, a word fixed | A new music track |
| Music on/off, louder/quieter, the switch point | |
| Text on screen, end card, size versions | |

Show it as one short list: "6 notes: 5 free, 1 needs a new clip (about 33¢). Go?" Free changes need no yes when the user is on key steps or autopilot; paid ones follow the hands-on setting and budget.

**4. Change only what the notes name.** Everything else stays exactly as it was (same clips, same timings). Save the next version (`_v2`, `_v3`). A change to `shots.json` that a hook shares (timing, a swapped clip) goes into each `shots_hook<letter>.json` too: run `hook.py` again with the same options plus `--force` to rebuild it from the new `shots.json` (free; its filled hook shots are kept).

**5. Check it again before sending:** `verify_vo.py`, then `variants.py` for the brief's sizes (the old sizes were cut from v1), then `qc.py`.

**6. Send v2 with a change list**, so they only re-watch what changed: "0:23 s08 clip swapped · captions moved lower · music quieter". Also write it to `changes.md`. Send a new shot map only if shots moved.

**7. Spot rules, not just fixes.** If a note sounds like it applies to every ad ("never put captions over faces", "always cut faster in the hook"), offer to save it to `house-rules.md` (or `brands/<brand>/learnings.md` for one brand). One line, only with a yes.

**If the voiceover changes** (a new take, a line rewritten): re-run `transcribe.py` on the new file, move each shot's start and end to its line's new times, keep every clip, and send the new draft with a shot map. Only shots whose line was rewritten need new visuals. Then run `hook.py` again for each hook with the same options plus `--force`, so its voiceover, words and shots follow the new take (`edit.py` and `verify_vo.py` flag a words file left over from the old one).

---

## Batch mode

When the user brings several briefs at once (a doc or a folder):

1. Stage 00 once.
2. Stages 1 to 4 for every ad, then show all the shot plans together for one approval. Each ad has its own project folder, so a budget is set inside each one (`check_setup.py --budget`); `generate.py spend` with no folder lists every ad's total.
3. Build the ads one after another. Keep `batch-status.md` up to date: each ad's stage (planned, frames, clips, edited, checked, delivered) and anything waiting on the user.

---

## Common problems and the rule that prevents them

| Problem | Prevention |
|---|---|
| Voiceover has gaps or drifts out of sync | The voiceover is never touched; `verify_vo.py` on every final |
| The character's face changes between shots | One master sheet; every version is an edit of it; one sheet per frame |
| Voice changes between talking clips | Generate the voiceover once, then lip-sync |
| The video tool changes the spoken words | Transcribe every talking clip and flag changes; `verify_vo.py` checks each talking shot's line (`"text"`) in the final; or use lip-sync |
| Captions show a word Whisper misheard (a brand name) | `transcribe.py --trust-script` for a generated voiceover; fix every `CHECK BY HAND` line for the user's own recording |
| Captions out of sync after a new take or a hook | Time each voiceover into its own words file (`hook.py` does it for hooks); `verify_vo.py` fails a words file from another take |
| Brand name misspelled on the product | Real product photo attached; best quality; check every product frame |
| Faces or product cut off in 4:5 feeds | 4:5 safe zone in every prompt, checked on every frame |
| The ad feels generic | Real moments from the buyer's day, with other people |
| Same shot feel twice in a row | No angle repeated back to back |
| Captions cover the face or sit under the app's buttons | Caption presets with safe positions; low on talking shots; moved off text cards by `edit.py` |
| Clip blocked by a safety filter | Soften the prompt (often a person + a medical detail), retry once, then ask |
| Veo says it was "unable to generate audio" | Reword the clip prompt: no brand names or written words, nothing that sounds like talking (ask, say, tell). Not charged |
| Provider busy | `generate.py` waits and retries by itself; failed jobs are normally not charged |
| A paid job timed out, lost the connection, was killed, or its download failed | `generate.py` keeps the provider's job id in `<out>.job.json` next to the file (e.g. `clips/s03.mp4.job.json`). When it says "the provider still has the job", run the same command again: the estimate shows the job as `$0.00 (finishing job <id>)` and the run collects it without paying again. Only when the error says the provider no longer has the job, or that it failed, does a re-run make (and pay for) a new one. Kie keeps jobs 14 days, Higgsfield about 7, Replicate only 1 hour. ElevenLabs returns the audio in the same call, so it has no job file. Only a job listed as "may have been made and charged anyway" needs a look at the provider's dashboard before running it again. Never delete `.job.json` files by hand |
| ElevenLabs stops with "characters for this month are used up (X left, Y needed)" | Tell the user: top up or upgrade at elevenlabs.io, shorten the script, or run again with `--provider kie`. "ELEVENLABS_API_KEY was refused" means a bad or revoked key: they make a new one |
| A run is BLOCKED by the budget or the per-run limit | Say what it would cost and what's left; ask before raising it (`check_setup.py --budget` / `--limit`) or making less |
| Credit runs out halfway | Stop, say so, finish with stills for missing shots, list them in the README |
| Clip opens on a frozen or storyboard frame | The contact sheet check; start the cut after it |
| A clip is shorter than its shot (the picture freezes) | `edit.py` stops and names it; `qc.py` fails a frozen clip shot. Smaller `in`, shorter shot, remake, or `"freeze_ok": true` |
| Size versions cut from an old draft | After every new version, run `variants.py` again; `qc.py` fails sizes made from an older 9:16 |
