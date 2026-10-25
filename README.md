# MyFlow

Hold a key, talk, let go. Clean text lands wherever your cursor is, in any Mac app. Runs 100% on your Mac. No subscription, no cloud, no account.

I was paying $240 a year for a dictation app. So I built this one with Claude and I'm giving it away. Filler words and stutters come out, names you teach it come out spelled right, and it learns from every fix you make.

## Will it run on my computer?

* **Yes:** a Mac with Apple Silicon (M1 or newer) on macOS 14 or later.
* **RAM:** 8 GB works, 16 GB is comfortable. MyFlow keeps about 2 GB in memory while it runs so the first word after a pause is as fast as the rest.
* **No:** Intel Macs, Windows, Linux. The speech models run on Apple's MLX and the rest is macOS plumbing. Windows and Linux folks: see [Not on a Mac?](#not-on-a-mac) below.

## Install with Claude (easiest)

Open Claude Code (or the Code tab in the Claude desktop app) and paste this:

```text
Clone https://github.com/Mightymouse43/myflow into ~/Developer/myflow and follow its CLAUDE.md to install MyFlow for me. If this computer is not an Apple Silicon Mac, use the design doc in docs/superpowers/specs/ to build the equivalent for my system instead.
```

Claude installs it, then asks you for the two clicks only you can do:

1. **Accessibility.** System Settings > Privacy & Security > Accessibility > turn on **MyFlow**. This is what lets it hear the key and paste the text.
2. **Microphone.** Click Allow the first time you hold the key.

Then hold **Right Option**, talk, let go.

## Install by hand

```bash
git clone https://github.com/Mightymouse43/myflow ~/Developer/myflow && ~/Developer/myflow/scripts/install.sh
```

The script installs what it needs (uv, Python 3.12, the 1.6 GB Whisper model), builds `~/Applications/MyFlow.app`, sets it to launch at login and starts it. If your Mac has never had Apple's command line tools, it opens that installer first and asks you to run it again after. Safe to re-run any time.

Health check:

```bash
~/Developer/myflow/.venv/bin/python -m voz doctor
```

## Using it

| Do this | MyFlow does this |
|---|---|
| Hold **Right Option**, talk, let go | Pastes the cleaned text at the cursor |
| Double-tap Right Option | Locks hands-free; tap once more to finish |
| Press Esc while listening | Cancels, nothing is pasted |
| Press any other key while holding | Also cancels (so Option+e accents never dictate) |
| Say "new line" or "new paragraph" | Inserts a line break or a blank line |

A small pill near the window you're typing into shows listening (live voice bars), thinking, done. If pasting is blocked (Accessibility missing, or a password field) the pill says "Copied" and the text is waiting on your clipboard.

"Um", "uh", "you know" and stutters like "the the" are removed. Turn that off in the menu if you want them. When you stop, think, and start again, MyFlow adds the space after your last sentence for you.

## Teaching it your words

* **Add a word:** menu > Add word to dictionary, or edit `~/.voz/dictionary.txt` (one entry per line). MyFlow reloads it within a few seconds.
  * `Figma` means: match anything that sounds like this and type it exactly like this.
  * `kube control => kubectl` means: when you hear the left side, type the right side.
* **Fix a dictation:** menu > Fix last dictation. Fix only the words it misheard. MyFlow turns each mishearing into a rule and adds new names to the dictionary. Rewording ("good" to "great") is deliberately not learned. See what it learned under Show learned corrections; wipe it with Forget learned corrections. Use this every time it misses and it stops missing.

## Engines

* **Whisper large-v3-turbo** (default): very accurate, under a second for 20 seconds of speech on an M-series Mac, and it takes your dictionary as a hint while it listens.
* **Parakeet v3**: faster, English and Spanish, less accurate on our tests. 2.5 GB download the first time you pick it in the Engine menu (or `scripts/install.sh --with-parakeet`).
* **Polish with local AI** (menu toggle, off by default): a small local language model tidies punctuation and false starts. Adds about a second. 1 GB download when you first switch it on.

Settings live in `~/.voz/config.toml` (hotkey: `right_option`, `right_command`, `right_control`, `fn`, `left_option`, `left_control`). For the Globe/Fn key, also set System Settings > Keyboard > "Press globe key to" = Do Nothing.

## Privacy

Nothing leaves your Mac. Audio is transcribed locally and the models are downloaded once from Hugging Face. Your dictations are logged to `~/.voz/history.jsonl` and the audio kept in `~/.voz/clips/` (capped at 2 GB) so "Fix last dictation" can learn from them. Set `save_clips = false` in `~/.voz/config.toml` to keep no audio.

## Not on a Mac?

The code is Mac-only, but the blueprint isn't. Paste this into Claude Code on your machine:

```text
Clone https://github.com/Mightymouse43/myflow and read CLAUDE.md and docs/superpowers/specs/2026-10-17-voz-local-dictation-design.md. Build the equivalent of MyFlow for my system (same behavior: hold a key, talk, release, clean text pasted at the cursor, all local). Reuse voz/textproc.py and voz/vocab.py as they are; swap the Mac-only parts for ones that work here.
```

Untested by me; the "porting" section of `CLAUDE.md` tells Claude which parts to swap.

## How I built it

With Claude Code, in an evening, from a written design and a step-by-step plan. Both are in the repo: `docs/superpowers/specs/` and `docs/superpowers/plans/`. `CLAUDE.md` has the map of the code and every gotcha we hit along the way, so your Claude starts where mine ended.

Under the hood: Python 3.12 in a uv venv, MLX speech models, CoreAudio for the mic, PyObjC for the floating pill, pasteboard and Accessibility, a Quartz event tap for the key, `rumps` for the menu bar. `MyFlow.app` is a 30-line Swift launcher that spawns the venv Python as a child so macOS attributes the permissions to "MyFlow" rather than "python3".

## Testing without a microphone

```bash
.venv/bin/python -m voz transcribe tests/fixtures/sample-20s.wav --raw
.venv/bin/python -m voz bench          # both engines on the sample clip, needs Parakeet downloaded
.venv/bin/pytest                       # fast suite
.venv/bin/pytest -m slow               # loads the speech models
```

## Uninstall

```bash
scripts/uninstall.sh          # removes the app and login item, keeps ~/.voz
scripts/uninstall.sh --purge  # also removes ~/.voz
```

## License

MIT. Use it, change it, share it.
