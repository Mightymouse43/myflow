# MyFlow: notes for the Claude installing or changing it

MyFlow is a free, local, hold-to-talk dictation app for Apple Silicon Macs (code name `voz`: the Python package, the `voz` command and the `~/.voz` folder keep the short name). The person asking you to install it is probably not a developer. Explain each step in one plain sentence, do the work yourself, and only hand them the two clicks macOS reserves for humans.

## Install (Apple Silicon Mac)

1. **Preflight.** `uname -m` must print `arm64` and `sw_vers -productVersion` must be 14 or newer. Intel Macs cannot run MLX; if this is not an Apple Silicon Mac, go to "Porting" below. Check for 5 GB of free disk.
2. **Command line tools.** If `xcode-select -p` fails, run `xcode-select --install`: macOS opens a dialog, the person clicks Install, it takes a few minutes. Wait for it, then continue.
3. **Run the installer** from the clone root: `scripts/install.sh`. It installs `uv` (Homebrew if present, otherwise the standalone installer), makes a Python 3.12 venv, installs the package, downloads the Whisper model (1.6 GB from Hugging Face, usually minutes, sometimes much longer on anonymous downloads; it resumes if re-run), compiles the tiny Swift launcher into `~/Applications/MyFlow.app`, registers a LaunchAgent and starts the app. Re-running is safe.
4. **The two clicks.** Tell the person:
   * System Settings > Privacy & Security > Accessibility > turn on **MyFlow** (the app opens that pane on first launch). Without it the app cannot hear the key or paste.
   * Hold Right Option once; macOS asks for the Microphone, click Allow.
5. **Verify.** `cat ~/.voz/status.json` shows `"trusted": true` and the text "Ready: hold Right Option and talk". `.venv/bin/python -m voz doctor` prints Accessibility granted and the model cached. Ask them to click into any text field, hold Right Option, say a sentence, let go. The text appears and `tail -3 ~/.voz/voz.log` shows a line like `9.5s audio -> 0.8s whisper: '...'`.

## Gotchas we already hit (save yourself the hour)

* **Never rebuild the launcher casually.** `scripts/build_app.sh` only replaces `~/Applications/MyFlow.app` when the launcher, plist, python path or icon changed, because a new ad-hoc signature makes macOS drop the Accessibility and Microphone grants. Python edits need no rebuild: `launchctl kickstart -k gui/$(id -u)/com.carlosramirez.myflow` restarts the app. If the grants ever go stale (ticked in Settings but not working), `tccutil reset Accessibility com.carlosramirez.myflow` and `tccutil reset Microphone com.carlosramirez.myflow`, restart, re-tick.
* **The pill says "Copied" instead of pasting:** Accessibility is not granted, or a password field or Terminal secure input has the keyboard. The text is on the clipboard.
* **Slow model download:** set `HF_HUB_DISABLE_XET=1` (the installer already does) and let it run; it resumes. A Hugging Face token speeds it up but is not required.
* **Mic:** capture goes through CoreAudio AudioQueue via ctypes (`voz/audio.py`). PortAudio/sounddevice deadlocks on macOS 26 at stream stop; do not bring it back for capture. A 3 s watchdog exits the process if a stop hangs and launchd restarts it.
* **MLX and threads:** unevaluated MLX arrays belong to the thread that created them. Any engine must `mx.eval` everything it builds at load time (`ParakeetEngine.load` does), or transcribing on the worker thread fails with "There is no Stream(cpu, N) in current thread".
* **A quiet microphone is normal.** A MacBook mic at a low input volume records speech near 0.006 RMS. The speech gate (`audio.is_speech`) judges a clip by its own dynamics (loud frames at least 3x the quiet ones, or over 0.02 RMS), never by an absolute floor: the first version's 0.004 floor silently dropped quiet takes as "Didn't catch that". The HUD meter calibrates the same way (its reference follows the loudest level heard, floor -40 dB) or the bars stay flat. Every dropped or cancelled take logs a `dropped:` or `cancelled` line in `~/.voz/voz.log`; read those before touching either threshold.
* **The app's own Cmd+V passes through the key tap too.** `paste._send_cmd_v` stamps its events with `hotkey.OWN_EVENT_TAG` (kCGEventSourceUserData) and the tap skips them; before that, a paste landing while the next dictation was already held read as a chord and cancelled it. The session also waits for the hotkey to come up before pasting (`HOLD_WAIT_S`).
* **The first take after a pause took 10 s:** macOS had paged the 1.6 GB of weights out to swap. `voz/residency.py` wires them after load (`mx.set_wired_limit`, macOS 15+) and clears MLX's scratch cache after every take, so idle MyFlow holds about 1.6 GB instead of 3.5 GB and never has to page the model back. `keep_model_resident = false` in config.toml turns the wiring off on a RAM-starved Mac.
* **Globe/Fn as the hotkey** also needs System Settings > Keyboard > "Press globe key to" = Do Nothing.
* **Diagnosing a hang:** `sample <pid> 2` and look for `__psynch_mutexwait`. Logs: `~/.voz/voz.log`, `~/.voz/launchd.err.log`.

## Map of the code

| File | What it does |
|---|---|
| `voz/app.py` | `Session` state machine (idle, listening, thinking, paste) on one worker thread; the `rumps` menu bar app; engine switching and background model downloads |
| `voz/audio.py` | AudioQueue recorder, speech energy gate, WAV reading |
| `voz/engines.py` | Whisper (mlx-whisper) and Parakeet (parakeet-mlx) behind one `transcribe()` |
| `voz/textproc.py` | Pure text: fillers, stutters, "new line", casing, punctuation, and `join_prefix` (the space between dictations) |
| `voz/vocab.py` | Dictionary, fuzzy matching, learning from "Fix last dictation" |
| `voz/paste.py` | Clipboard-safe Cmd+V, secure input check, reading the character before the caret through Accessibility |
| `voz/hud.py` | The floating pill with live voice bars, anchored to the window you dictate into |
| `voz/hotkey.py` | Quartz event tap for the hold / double-tap / cancel gestures |
| `voz/polish.py` | Optional local LLM cleanup (mlx-lm) |
| `voz/history.py`, `voz/config.py`, `voz/status.py`, `voz/launchagent.py`, `voz/doctor.py` | Logs and clips, `~/.voz/config.toml`, `status.json`, login item, health check |
| `launcher/MyFlow.swift`, `scripts/build_app.sh` | The app bundle: a Mach-O launcher that spawns the venv Python so permissions attach to "MyFlow" |
| `scripts/install.sh`, `scripts/uninstall.sh` | One-shot install and removal |
| `docs/superpowers/specs/`, `docs/superpowers/plans/` | The design and the step-by-step plan the first version was built from |

Tests: `.venv/bin/pytest` (fast, about 10 s) and `.venv/bin/pytest -m slow` (loads the speech models). Write the failing test first; the suite is how this project stays honest.

## Porting (Windows, Linux, Intel Mac)

The behavior contract is in `docs/superpowers/specs/2026-10-17-voz-local-dictation-design.md`: hold a key, talk, release; local speech to text; fillers and stutters removed; a user dictionary applied exactly then fuzzily; a space added when a dictation follows text; paste at the caret with the clipboard restored; a small always-on-top status pill; a tray or menu bar icon; a login item.

Keep as-is (pure Python, tested, platform-free): `voz/textproc.py`, `voz/vocab.py`, `voz/history.py`, `voz/config.py`, `tests/test_textproc.py`, `tests/test_vocab.py`.

Swap:

* **Speech engine:** `faster-whisper` (CUDA or CPU) or `whisper.cpp` bindings in place of mlx-whisper. Keep the `Engine` protocol in `voz/engines.py` (`load()`, `transcribe(audio, sr, prompt_words)`), and `mx.eval`-style thread care does not apply.
* **Mic:** `sounddevice` is fine off macOS (one `InputStream` per key hold).
* **Hotkey:** a global hotkey library (`pynput` works on Windows and X11; on Wayland use the desktop's shortcut system to call a small command).
* **Paste:** set the clipboard, send Ctrl+V through the OS input API (`pynput` or `pyautogui`), restore the clipboard after a short delay. Reading the character before the caret uses UI Automation on Windows; fall back to the "recent paste into the same app" guess in `Session._join_prefix` when that is unavailable.
* **Pill and tray:** a borderless always-on-top window (Tk, Qt or `pywebview`) and `pystray`.
* **Login item:** Task Scheduler or a Startup folder shortcut on Windows, a `systemd --user` unit or autostart `.desktop` on Linux.

Untested outside macOS. Build it test-first and keep the user's dictionary format (`~/.voz/dictionary.txt`) so the docs still apply.
