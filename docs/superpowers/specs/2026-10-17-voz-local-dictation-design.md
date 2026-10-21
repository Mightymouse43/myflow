# Voz: local, free, Wispr Flow-style dictation for Carlos's Mac

Date: 2026-10-17. Author: Claude (brainstorm skipped by Carlos's /goal directive; every "how" choice below is Claude's call unless marked as Carlos's).

## Intent and why
Carlos wants Wispr Flow without the subscription. Hold a key, talk, release, and clean text lands wherever the cursor is, in any app. It must run fully on his Mac (M3 Pro, 18 GB, macOS 26.5), be fast enough to feel instant, strip filler words, let him add his own vocabulary, and get better the more he uses it.

## Goals (Carlos's)
1. Works in any app on the Mac (push-to-talk key, text pasted at the cursor).
2. Fully local, no monthly cost.
3. Fast and responsive.
4. Removes dead words ("uh", "um", repeats) as he speaks.
5. Custom dictionary he can add words to.
6. Adapts to the way he speaks over time.

## Non-goals (v1)
* Windows/Linux, iPhone.
* Live word-by-word streaming into the text field (Wispr pastes on release too; same here).
* Meeting transcription / long recordings. This is for utterances of a few seconds to a couple of minutes.
* A signed, notarized Mac App Store build.

## Anti-goals (would make it a failure)
* Needing a cloud key or a subscription for any core path.
* Latency over ~1.5 s for a 10 s utterance.
* Pasting over the user's clipboard and losing what was there.
* Garbling proper nouns he uses daily (Tenants2Guest, OwnerRez, HyperFrames, Claude, Higgsfield).

## Constraints
* Apple Silicon only (MLX). macOS needs Accessibility granted to the app for key capture and paste; Microphone on first use. Only Carlos can click those.
* Mac disk is tight at times; models cached under `~/.cache/huggingface`, keep total under ~3 GB.
* Carlos's house rules: no em dashes in copy, plain friendly tone, no corporate speak.

## How it gets made (Claude's calls)
* **Language/runtime:** Python 3.12 in a uv venv at `~/Developer/voz/.venv`. Native-feeling UI via PyObjC (AppKit/Quartz), menu bar via `rumps`.
* **Speech engines (both shipped, one default):**
  * `parakeet-mlx` with `mlx-community/parakeet-tdt-0.6b-v3` (English + Spanish + 23 more, punctuation built in, very fast).
  * `mlx-whisper` with `mlx-community/whisper-large-v3-turbo` (already cached on this Mac; supports vocabulary biasing via `initial_prompt`).
  * Default chosen by a measured benchmark on a real recording (the public repo ships a synthetic clip) (`tests/fixtures/sample-20s.wav`): accuracy first, then latency.
* **Hotkey:** Quartz CGEventTap on `flagsChanged`/`keyDown`. Default key: **Right Option (⌥)** hold-to-talk. Double-tap locks hands-free; tap again or Esc to stop. Fn/Globe, Right Command, Right Control selectable in config.
* **Audio:** `sounddevice`, 16 kHz mono, default input device, buffered in RAM while the key is held. Short beep-free; HUD shows state instead.
* **Text injection:** write to NSPasteboard, synthesize Cmd+V via CGEvent, restore the previous clipboard contents ~0.4 s later. Fallback when paste is blocked: leave text on the clipboard and say so in the HUD.
* **HUD:** small non-activating NSPanel pill at bottom-centre: "Listening", "Thinking", then the pasted text for 1.5 s. Menu bar icon mirrors state.
* **Text pipeline (pure Python, unit-tested):**
  1. Filler removal: um, uh, erm, hmm, ah, "you know" (configurable list; "like" off by default because it is often real).
  2. Stutter/repeat collapse ("the the", "I I think").
  3. Spoken commands: "new line", "new paragraph", optional "period/comma" when they end a phrase.
  4. Dictionary: `~/.voz/dictionary.txt`, one entry per line, `Word` or `heard form => Correct Form`. Applied exactly, then fuzzily (RapidFuzz + metaphone on 1 to 3 word windows) so "tenants to guest" becomes "Tenants2Guest". Also fed to Whisper as the biasing prompt.
  5. Learned corrections: `~/.voz/learned.json`, applied like dictionary rules.
  6. Capitalisation and terminal punctuation guard.
* **Adaptation ("learns how I speak"):**
  * Every dictation logged to `~/.voz/history.jsonl` (raw text, final text, app, duration).
  * "Fix last dictation" (menu item) opens the last text for editing; the diff becomes learned rules immediately, and new capitalised words go straight into the dictionary.
  * Audio + final text pairs kept under `~/.voz/clips/` (cap 2 GB, oldest pruned) as the training set for a future Whisper LoRA fine-tune. The fine-tune itself is out of scope for v1 and is said so plainly.
  * Optional **Polish** mode: local LLM (`mlx-lm`, Qwen2.5-1.5B-Instruct 4-bit, ~1 GB, downloaded on first enable) rewrites punctuation and false starts using the dictionary and the last 20 accepted dictations as style examples. Off by default because it adds ~0.5 to 1 s.
* **Packaging:** `Voz.app` bundle at `~/Applications/Voz.app` whose executable is a tiny compiled Swift launcher that spawns the venv Python (child process, so macOS attributes Microphone/Accessibility permissions to "Voz", not to "python3"). `LSUIElement` so no Dock icon. Ad-hoc code signed. LaunchAgent for launch at login. One `install.sh` does all of it.
* **Config:** `~/.voz/config.toml` (hotkey, engine, language, fillers, polish on/off, clip retention).
* **CLI for testing without a mic:** `voz transcribe <wav>` runs the full pipeline and prints the text; `voz doctor` reports permissions, model cache, and audio devices.

## Left to the builder
* Exact HUD styling, icon glyphs.
* Benchmark harness details and the WER threshold that picks the default engine.
* How the Fix window is drawn (rumps.Window is acceptable).

## What only Carlos can do
1. Click Allow on the Microphone prompt and add Voz under System Settings > Privacy & Security > Accessibility (the app opens that pane on first run).
2. If he wants the Globe/Fn key: System Settings > Keyboard > "Press 🌐 key to" = Do Nothing.
3. Tell us the words he wants in the dictionary beyond the seed list, and which hotkey he prefers.
4. Use it for a week and hit "Fix last dictation" when it gets something wrong; that is the learning loop.
