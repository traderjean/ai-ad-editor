# AI Ad Editor

**A free Claude skill that turns your ad script into a finished video ad, from AI clips, your own clip library, or both. Built for [Kie.ai](https://kie.ai), and also works with [Replicate](https://replicate.com) and [Higgsfield](https://higgsfield.ai).**

Paste a script. Claude plans every shot, makes the characters, images, clips and voiceover with the AI tools you already use (or finds the right clips in your library), cuts it to the voiceover with captions and music, and checks every file before it hands it over. You approve each step in chat, and nothing that costs money runs without your yes.

---

## What you get

- **A finished 9:16 ad**, cut frame-accurately to the voiceover, with captions, music and an end card
- **Your clips, AI clips, or both**: make every shot with AI, cut the ad from your own clip library, or mix them (library first, AI fills the gaps). Library-only edits cost nothing to make
- **Hook variants**: write your own hook lines or pick from suggestions. Each one is cut onto the same ad
- **Every size**: 9:16, 4:5, 1:1 and 16:9 from the same edit
- **The same character in every shot**: one master character sheet, with every other version edited from it
- **Any kind of voiceover**: your own file, a generated voice, characters talking on screen, an AI presenter, or text on screen with no voice
- **Checks before delivery**: the voiceover is matched word for word, plus frozen frames, black frames, sizes and file specs
- **Easy revisions**: every draft comes with a shot map (time, shot and line for each shot). Give notes by time, line or description. Claude sorts them into free edits and paid remakes, shows the cost before changing anything, and sends v2 with a list of what changed
- **Music that sits under the voice**: your track dips automatically while someone speaks, and you can switch to a second track at any line

## How it works

| Step | What happens | You |
|---|---|---|
| 1. Setup | Asks where clips come from (AI, your library, or both), finds your AI tools and keys, and remembers them | Confirm once |
| 2. Brief and look | Reads your brief, asks only for what's missing | Approve one summary |
| 3. Voiceover | Use yours or generate one | Approve it |
| 4. Timing | Every word gets a time, so cuts land on the words | — |
| 5. Shot plan and hooks | A shot-by-shot plan showing where each shot comes from (AI or your library), plus a card for each hook | Approve (free to change) |
| 6. Characters | 3 different people who fit your buyer (AI shots only) | Pick one |
| 7. Start frames | One test frame, then a grid of all of them (AI shots only) | Approve |
| 8. Clips | 1 or 2 test clips, then the rest, each checked frame by frame (AI shots only) | Approve |
| 9. Edit | Captions, music, end card | Review the ad |
| 10. Variants and delivery | Hooks, sizes, final checks, a summary file | Download |

## Fits how you already work

- **Choose how hands-on you are.** Approve every step, approve only the key steps (brief, shot plan, final), or let it make the whole ad on autopilot inside a budget you set.
- **Start wherever you are.** Bring just a script, a script and voiceover, your own shot plan, or your own frames and clips. It picks up from there.
- **Write your house rules once.** Fill in [`house-rules-template.md`](house-rules-template.md): approvals, team, default look, voice and captions, file naming, where finished files go, and anything you always or never do. Claude follows it on every ad and adds to it when you tell it something new.
- **It remembers each brand.** Product, buyer, look and feedback are saved per brand, so the next ad only needs the script.

## Built for Kie.ai, also works with Replicate and Higgsfield

This skill is built for [Kie.ai](https://kie.ai) and tested on it. One Kie key and one balance cover the images, video clips, lip-sync and talking avatars. If you want generated voiceovers, add an [ElevenLabs](https://elevenlabs.io) key too.

**Two more ready-made options**, picked at setup. You can mix them: each job (images, video, voice, music, lip-sync) can use a different one.

| | What it covers | Key |
|---|---|---|
| [Kie.ai](https://kie.ai) (default) | Images, video, voiceover, music, lip-sync, talking avatars | `KIE_API_KEY` |
| [Replicate](https://replicate.com) | Images, video, voiceover, music, lip-sync, talking avatars. Pay per result, many models to choose from | `REPLICATE_API_TOKEN` |
| [Higgsfield](https://higgsfield.ai) API | Images and video | `HF_KEY` (key ID and secret as `id:secret`) |
| Higgsfield MCP | Images, video, voiceover and lip-sync, from inside Claude (paid in Higgsfield credits) | Connect the Higgsfield connector in Claude |

**Prefer something else?** You can still use another API or any connected MCP that makes images, video or audio instead. Claude checks what you have at setup. With no tools at all, Claude writes each prompt for you to run by hand in any app, and carries on when you send the result back.

## Quick start

**1. Install**

```bash
git clone https://github.com/tom-surge/ai-ad-editor.git ~/.claude/skills/ai-ad-editor
pip3 install -r ~/.claude/skills/ai-ad-editor/requirements.txt
```

**2. Add your keys** to your shell profile (for example `~/.zshrc`), never in chat:

```bash
export KIE_API_KEY="..."
export ELEVENLABS_API_KEY="..."   # optional, for generated voiceovers
export REPLICATE_API_TOKEN="..."  # optional, to use Replicate
export HF_KEY="<key id>:<secret>" # optional, to use the Higgsfield API
```

On Windows (PowerShell), then open a new terminal:

```powershell
setx KIE_API_KEY "..."
setx ELEVENLABS_API_KEY "..."   # optional
setx REPLICATE_API_TOKEN "..."  # optional
setx HF_KEY "<key id>:<secret>" # optional
```

On Windows the skill folder is `%USERPROFILE%\.claude\skills\ai-ad-editor`, and the commands are `python` instead of `python3` and `pip` instead of `pip3`.

No keys? That's fine: by-hand mode works with any app.

**3. Fill in [`brief-template.md`](brief-template.md)**, then open Claude and say:

> **Edit this ad**

and paste your brief. The must-haves are your script, the product (name, what it does, 1 to 3 photos), the buyer and their problem, and your voiceover choice. Everything else has a default.

## What it costs

You pay your AI tools directly. The skill itself is free. Rough prices on Kie.ai:

| Item | Approx |
|---|---|
| Image (character sheet, start frame) | $0.05 to $0.09 |
| 8-second video clip (Veo 3.1 Fast) | $0.33 |
| Lip-sync a talking shot | $0.16 |
| A 30-second ad (about 10 clips) | about $4 |
| A 60-second ad with 3 hooks | about $8 to $10 |

On Replicate and Higgsfield, video is billed per second, so asking for each shot's own length (`--fit`) costs less than the full 8 seconds:

| Item | Replicate | Higgsfield API |
|---|---|---|
| Image | $0.03 to $0.15 (Nano Banana 2.1 / Pro) | $0.04 to $0.08 (best tier: no published price) |
| 8-second clip, standard quality, no sound | $0.80 (Veo 3.1 Fast) | $0.64 (Wan 3.0, 1080p) |
| The same clip at 4 seconds (`--fit`) | $0.40 | $0.32 |
| Lip-sync a talking shot | $0.16 to $0.33 for a 4-second line | Higgsfield MCP only |
| Voiceover, 60 seconds | about $0.09 (ElevenLabs v3) | Higgsfield MCP only |
| A 30-second ad (about 10 clips) | about $9, or about $5 with `--fit` | about $7, or about $4 with `--fit` |

Claude shows the estimate before every paid run, and you can set a per-run spending limit.

## Requirements

- [Claude Code](https://claude.com/claude-code), or any Claude app that loads skills and can run commands
- Mac, Windows or Linux
- Python 3.9+ with `faster-whisper`, `imageio-ffmpeg`, `pillow` and `numpy` (`imageio-ffmpeg` gives you ffmpeg if you don't have it)
- At least one way to make images and video: an API key, an MCP, or by hand

The first time it times a voiceover, it downloads a small speech model. That takes about a minute, once.

## What's in here

| File | What it is |
|---|---|
| `SKILL.md` | The instructions Claude follows: every step, rule and approval |
| `brief-template.md` | The brief you fill in |
| `requirements.txt` | The Python packages to install |
| `house-rules-template.md` | Optional: how you or your team work, followed on every ad |
| `guides/phone-look-guide.md` | How to make AI frames look like real phone footage |
| `scripts/check_setup.py` | Finds your tools and keys, and saves which tool does which job (free) |
| `scripts/generate.py` | One command for every image, clip, voiceover, lip-sync, avatar and music track |
| `scripts/providers/` | One small file per AI service |
| `scripts/transcribe.py` | Word timings and a first draft of the shots |
| `scripts/edit.py` | Cuts the ad: shots on the voiceover, captions, music, end card |
| `scripts/library.py` | Indexes your clip library, finds clips for each line, and tracks which were used |
| `scripts/contact_sheet.py` | Frames from every clip on one page, for checking |
| `scripts/shot_map.py` | The shot map that comes with every draft, for giving notes |
| `scripts/verify_vo.py` | Checks the voiceover is in the final, word for word |
| `scripts/variants.py` | 4:5, 1:1 and 16:9 versions |
| `scripts/qc.py` | Final checks on every file before delivery |

## Add another AI service

Copy `scripts/providers/kie.py` (or `replicate.py` / `higgsfield.py`), set `name`, `env_key` and `slots`, write the methods for the jobs it does (`image`, `video`, `voice`, `lipsync`, `avatar`), and add it to `ALL` in `scripts/providers/__init__.py`. Run `python3 scripts/check_setup.py` and it shows up. Pull requests for new services are welcome.

## FAQ

**Does it write the script?** No. It starts from a finished script and never rewrites it.

**Can I use my own footage?** Yes. Point it at a folder of clips you own or have the rights to. Claude looks through every clip once, describes it in plain words, picks the best clip for each line, and remembers which clips earlier ads used so they don't repeat. In mixed mode, any line with no good clip is made with AI, matched to the people in your footage.

**Does library mode cost anything?** No. It only uses your own clips, so the only cost is an optional generated voiceover.

**Will the character look the same in every shot?** That's what the master character sheet is for. Every frame is made from it, and every clip from its frame.

**What if a clip comes out wrong?** Claude checks every clip, tells you which ones it suggests remaking and why, and remakes only the ones you say yes to.

**How do I give notes on a draft?** Use the shot map that comes with it: say the time, the line or just describe the shot. Changes to cuts, captions and music are free; anything that needs a new image or clip shows its cost first.

**What if my credits run out halfway?** It stops and tells you. It can finish the edit with still images for the missing shots and lists them, so you always get a complete ad.

## License

MIT. See [LICENSE](LICENSE).
