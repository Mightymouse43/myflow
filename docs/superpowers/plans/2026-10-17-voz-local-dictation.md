# Voz Local Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A menu bar Mac app: hold Right Option, talk, release, and cleaned text is pasted at the cursor in any app, fully offline, with a personal dictionary and a correction loop that learns.

**Architecture:** One Python process (rumps menu bar app on the AppKit main loop) owns a state machine: idle -> listening (sounddevice buffer) -> thinking (MLX engine on a worker thread) -> text pipeline -> paste. Pure-Python modules (textproc, vocab, history) are unit-tested; macOS glue (hotkey tap, pasteboard, HUD) is thin. A compiled Swift launcher inside `Voz.app` spawns the venv Python so macOS permission prompts name "Voz".

**Tech Stack:** Python 3.12 (uv venv), parakeet-mlx, mlx-whisper, sounddevice, numpy, rapidfuzz, rumps, PyObjC (Cocoa, Quartz), pytest, Swift launcher, launchd.

**Spec:** `docs/superpowers/specs/2026-10-17-voz-local-dictation-design.md`

## Global Constraints
* Python 3.12 venv at `~/Developer/voz/.venv`; run everything as `.venv/bin/python -m voz ...` or `.venv/bin/pytest`.
* No cloud calls anywhere in the core path.
* Models: `mlx-community/parakeet-tdt-0.6b-v3` and `mlx-community/whisper-large-v3-turbo`; total model cache under ~3 GB.
* User state lives in `~/.voz/` (`config.toml`, `dictionary.txt`, `learned.json`, `history.jsonl`, `clips/`).
* Default hotkey: Right Option (keycode 61), hold to talk, double-tap to lock, Esc cancels.
* Copy rules: no em dashes anywhere in UI strings or docs; friendly plain English.
* Commit after each task.

## Review Focus
1. Accidental tap or silence: nothing is pasted and no hallucinated sentence appears. Test in Task 6 (`test_is_speech_false_for_silence`) and Task 5 (`test_whisper_silence_returns_empty`).
2. Clipboard safety: whatever was on the clipboard before (text or an image) is back after the paste. Test in Task 7 (`test_pasteboard_snapshot_roundtrip_image`).
3. Fast back-to-back dictations: a new hold while the previous one is still transcribing still records, and texts paste in order. Test in Task 8 (`test_two_quick_dictations_paste_in_order`).
4. Dictionary entries with odd characters (`Tenants2Guest`, `C++`, `OwnerRez => OwnerRez`) never raise and apply literally. Test in Task 3 (`test_special_chars_in_entry`).
5. Paste blocked (Accessibility missing or secure input): text is left on the clipboard and the HUD says so instead of silently vanishing. Test in Task 7 (`test_paste_returns_copied_when_untrusted`).

---

### Task 1: Project skeleton and config

**Files:**
- Create: `pyproject.toml`, `voz/__init__.py`, `voz/__main__.py`, `voz/config.py`, `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.VOZ_DIR: Path` (= `~/.voz`, overridable by env `VOZ_HOME`), `config.load() -> Config` dataclass with fields `hotkey: str = "right_option"`, `engine: str = "parakeet"`, `language: str = "en"`, `fillers: list[str]`, `remove_fillers: bool = True`, `spoken_commands: bool = True`, `polish: bool = False`, `clip_retention_mb: int = 2048`, `paste_restore_delay_ms: int = 400`; `config.save(cfg)`; `config.ensure_dirs()` creates `~/.voz` and `clips/` and writes a default `dictionary.txt` if missing.
- `python -m voz` dispatches subcommands `run`, `transcribe`, `doctor`, `bench` (stubs that print "not implemented" until later tasks).

- [ ] **Step 1: Write failing tests**

```python
def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import importlib, voz.config as c; importlib.reload(c)
    cfg = c.load()
    assert cfg.hotkey == "right_option" and cfg.engine == "parakeet"
    assert "um" in cfg.fillers and "like" not in cfg.fillers

def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import importlib, voz.config as c; importlib.reload(c)
    cfg = c.load(); cfg.engine = "whisper"; c.save(cfg)
    assert c.load().engine == "whisper"
    assert (tmp_path / "config.toml").exists()

def test_ensure_dirs_seeds_dictionary(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import importlib, voz.config as c; importlib.reload(c)
    c.ensure_dirs()
    assert (tmp_path / "clips").is_dir()
    assert "Tenants2Guest" in (tmp_path / "dictionary.txt").read_text()
```

- [ ] **Step 2: Run `.venv/bin/pytest tests/test_config.py -v`; expect ImportError.**
- [ ] **Step 3: Implement `voz/config.py`** (tomllib to read, hand-written TOML writer for the flat dataclass; default fillers `["um","uh","uhm","erm","hmm","mm","ah","you know"]`; seed dictionary = the list in Task 11 kept in `config.SEED_DICTIONARY`).
- [ ] **Step 4: Run tests; expect PASS.**
- [ ] **Step 5: Commit `feat: project skeleton and config`.**

### Task 2: Text cleanup (fillers, repeats, spoken commands)

**Files:**
- Create: `voz/textproc.py`
- Test: `tests/test_textproc.py`

**Interfaces:**
- Produces: `textproc.remove_fillers(text: str, fillers: list[str]) -> str`, `textproc.collapse_repeats(text: str) -> str`, `textproc.apply_spoken_commands(text: str) -> str`, `textproc.tidy(text: str) -> str` (capitalise first letter of each sentence, collapse double spaces, fix space before punctuation, ensure a final period only if the text has 3+ words and ends with a letter or digit), `textproc.clean(text: str, cfg: Config) -> str` (runs the four in that order, respecting `cfg.remove_fillers` and `cfg.spoken_commands`).

- [ ] **Step 1: Write failing tests**

```python
F = ["um","uh","erm","hmm","you know"]
def test_removes_fillers_case_and_punct():
    assert remove_fillers("Um, so I think, uh, we should go.", F) == "So I think we should go."
def test_filler_inside_word_untouched():
    assert remove_fillers("The drum and the humming.", F) == "The drum and the humming."
def test_multiword_filler():
    assert remove_fillers("It was, you know, fine.", F) == "It was fine."
def test_collapse_repeats():
    assert collapse_repeats("I I think the the plan is is good") == "I think the plan is good"
def test_repeat_keeps_intentional_pairs():
    assert collapse_repeats("that that") == "that"  # documented tradeoff
    assert collapse_repeats("bye bye") == "bye bye"  # allowlist: bye, very, no, so
def test_spoken_newline_and_paragraph():
    assert apply_spoken_commands("first point new line second point new paragraph third") == "first point\nsecond point\n\nthird"
def test_tidy_capitalises_and_ends():
    assert tidy("hello there. how are you") == "Hello there. How are you."
def test_tidy_leaves_short_fragments_alone():
    assert tidy("ok") == "Ok"
def test_clean_pipeline():
    cfg = Config(); assert clean("um so the the plan new line is good", cfg) == "So the plan\nis good."
```

- [ ] **Step 2: Run tests; expect ImportError.**
- [ ] **Step 3: Implement `voz/textproc.py`** with word-boundary regexes built from the filler list (escape each; longest first; strip a trailing comma after the removed filler and leading comma/space before it).
- [ ] **Step 4: Run tests; expect PASS.**
- [ ] **Step 5: Commit `feat: text cleanup pipeline`.**

### Task 3: Vocabulary (dictionary + learned corrections)

**Files:**
- Create: `voz/vocab.py`
- Test: `tests/test_vocab.py`

**Interfaces:**
- Consumes: `config.VOZ_DIR`.
- Produces: `vocab.parse_dictionary(text: str) -> list[Rule]` where `Rule(heard: str | None, canonical: str)`; `vocab.Vocab` class with `.rules`, `.learned` (loaded from `dictionary.txt` + `learned.json`), `.apply(text: str) -> str` (exact rules first, then fuzzy: for each canonical, scan 1..n-word windows, lowercase, `rapidfuzz.fuzz.ratio >= 88` or equal metaphone codes, replace preserving following punctuation; never touch windows shorter than 4 characters), `.words() -> list[str]` (for Whisper prompt), `.learn(raw: str, corrected: str) -> list[Rule]` (difflib on word tokens; each replaced span becomes `Rule(heard, corrected)` appended to `learned.json`; any corrected token starting uppercase that is not sentence-initial is added to `dictionary.txt` if absent), `.add_word(word: str)`.

- [ ] **Step 1: Write failing tests**

```python
def test_parse_plain_and_mapped():
    r = parse_dictionary("Tenants2Guest\nowner res => OwnerRez\n# comment\n\n")
    assert r == [Rule(None,"Tenants2Guest"), Rule("owner res","OwnerRez")]
def test_exact_mapping_applies(tmp_voz):
    v = Vocab.from_text("owner res => OwnerRez")
    assert v.apply("log into owner res today.") == "log into OwnerRez today."
def test_fuzzy_single_word(tmp_voz):
    v = Vocab.from_text("Higgsfield")
    assert v.apply("render it in hicksfield tonight") == "render it in Higgsfield tonight"
def test_fuzzy_multiword_window(tmp_voz):
    v = Vocab.from_text("Tenants2Guest")
    assert v.apply("tenants to guest is growing") == "Tenants2Guest is growing"
def test_short_words_not_fuzzed(tmp_voz):
    v = Vocab.from_text("Claude")
    assert v.apply("cloud cover and clod") == "cloud cover and clod"  # ratio < 88 for 'clod'; 'cloud' must map
    assert v.apply("ask cloud about it") == "ask Claude about it"
def test_special_chars_in_entry(tmp_voz):
    v = Vocab.from_text("C++\nTenants2Guest\n(beta) => beta")
    assert v.apply("c++ and (beta) here") == "C++ and beta here"
def test_learn_records_rule_and_new_proper_noun(tmp_voz):
    v = Vocab.from_text("")
    rules = v.learn("send it to ximena at the hyper frames kit", "send it to Ximena at the HyperFrames kit")
    assert Rule("hyper frames","HyperFrames") in rules
    assert "Ximena" in v.words() and "HyperFrames" in v.words()
    assert Vocab.load().apply("the hyper frames kit") == "the HyperFrames kit"
```
(`tmp_voz` fixture in `tests/conftest.py` sets `VOZ_HOME` to `tmp_path` and reloads `voz.config`.)

- [ ] **Step 2: Run tests; expect ImportError.**
- [ ] **Step 3: Implement `voz/vocab.py`** (use `rapidfuzz.fuzz.ratio` and a small built-in metaphone or `rapidfuzz.distance.Levenshtein`; windows up to 3 words; apply longest canonical first).
- [ ] **Step 4: Run tests; expect PASS.**
- [ ] **Step 5: Commit `feat: personal dictionary with fuzzy matching and learning`.**

### Task 4: History and clip store

**Files:**
- Create: `voz/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Produces: `history.append(raw: str, final: str, app: str, seconds: float, clip: Path | None) -> dict`, `history.last() -> dict | None`, `history.recent(n: int) -> list[dict]`, `history.save_clip(audio: np.ndarray, sr: int) -> Path` (16-bit WAV under `clips/YYYYMMDD-HHMMSS.wav`), `history.prune_clips(max_mb: int) -> int` (oldest first, returns files removed), `history.update_last_final(final: str)`.

- [ ] **Step 1: Write failing tests**: append then `last()` returns the record with `final`; `recent(2)` ordering newest first; `save_clip` writes a readable WAV with the right frame count; `prune_clips(0)` after two clips removes both and returns 2; `update_last_final` rewrites only the last line.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement with jsonl append and `wave` module.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit `feat: history log and clip store`.**

### Task 5: Speech engines and benchmark

**Files:**
- Create: `voz/engines.py`, `voz/bench.py`
- Modify: `voz/__main__.py` (`transcribe`, `bench` subcommands)
- Test: `tests/test_engines.py` (marked `slow`)

**Interfaces:**
- Produces: `engines.Engine` protocol: `.name: str`, `.load() -> None`, `.transcribe(audio: np.ndarray, sr: int, prompt_words: list[str] | None = None) -> str`. `engines.ParakeetEngine`, `engines.WhisperEngine` (passes `initial_prompt=", ".join(prompt_words)` and `language=cfg.language`, `condition_on_previous_text=False`, `no_speech_threshold=0.6`, returns "" when every segment has `no_speech_prob > 0.6`). `engines.load_engine(cfg: Config) -> Engine`. `bench.wer(ref: str, hyp: str) -> float`, `bench.run(wav: Path, ref: Path) -> list[dict(name, wer, seconds)]`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.slow
@pytest.mark.parametrize("name", ["parakeet","whisper"])
def test_engine_on_carlos_sample(name):
    eng = load_engine(Config(engine=name)); eng.load()
    audio, sr = read_wav(FIX/"sample-20s.wav")
    hyp = eng.transcribe(audio, sr)
    assert wer((FIX/"sample-20s.ref.txt").read_text(), hyp) < 0.15
@pytest.mark.slow
def test_whisper_silence_returns_empty():
    eng = load_engine(Config(engine="whisper")); eng.load()
    assert eng.transcribe(np.zeros(16000, dtype=np.float32), 16000).strip() == ""
def test_wer():
    assert wer("a b c d", "a b x d") == 0.25
```

- [ ] **Step 2: Run `.venv/bin/pytest tests/test_engines.py -v -m slow`; expect ImportError.**
- [ ] **Step 3: Implement `voz/engines.py` and `voz/bench.py`; wire `python -m voz transcribe <wav> [--engine]` (prints final text after `textproc.clean` + `Vocab.apply`) and `python -m voz bench` (prints a table).**
- [ ] **Step 4: Run the tests and `python -m voz bench`; record the numbers in the plan's Task 5 notes; set `Config.engine` default to the winner (lowest WER; if within 2 points, the faster one).**
- [ ] **Step 5: Commit `feat: parakeet and whisper engines, benchmark`.**

### Task 6: Microphone recorder

**Files:**
- Create: `voz/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces: `audio.Recorder(sr: int = 16000)` with `.start()`, `.stop() -> np.ndarray` (float32 mono), `.seconds: float`, `.level: float` (latest RMS for the HUD); `audio.is_speech(audio: np.ndarray, threshold: float = 0.004) -> bool` (RMS gate); `audio.read_wav(path) -> tuple[np.ndarray, int]`.

- [ ] **Step 1: Write failing tests**: `test_is_speech_false_for_silence` (zeros -> False) and `test_is_speech_true_for_fixture` (sample-20s.wav -> True); `test_recorder_half_second` (start, sleep 0.5, stop -> shape between 0.4 s and 0.7 s of samples at 16 kHz; skipped if no input device).
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement with `sounddevice.InputStream` callback appending blocks to a list; `stop()` concatenates.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit `feat: microphone recorder`.**

### Task 7: Paste and hotkey glue

**Files:**
- Create: `voz/paste.py`, `voz/hotkey.py`
- Test: `tests/test_paste.py`, `tests/test_hotkey.py`

**Interfaces:**
- Produces: `paste.is_trusted() -> bool` (`AXIsProcessTrusted`), `paste.request_trust()` (`AXIsProcessTrustedWithOptions` with prompt), `paste.snapshot_pasteboard() -> list[tuple[str, bytes]]`, `paste.restore_pasteboard(snap)`, `paste.paste_text(text: str, restore_delay_ms: int) -> Literal["pasted","copied"]` ("copied" when untrusted or the CGEvent post fails; text stays on the clipboard in that case).
- `hotkey.KEYCODES = {"right_option":61,"right_command":54,"right_control":62,"fn":63}`; `hotkey.HoldDetector(on_start, on_stop, on_cancel, double_tap_ms=350)` with `.feed(keycode: int, down: bool, now: float)` pure state machine: hold -> `on_start` on down, `on_stop` on up; two taps within `double_tap_ms` -> locked (`on_start` once, stays until next tap -> `on_stop`); `feed(53, True)` (Esc) while active -> `on_cancel`. `hotkey.Listener(detector, keycode)` wraps a Quartz `CGEventTapCreate` (listen-only, `flagsChanged` + `keyDown`) on its own thread run loop; `.start()` returns False with a logged reason if the tap could not be created.

- [ ] **Step 1: Write failing tests**: `test_pasteboard_snapshot_roundtrip_text` (write "before", snapshot, write "x", restore, read "before"); `test_pasteboard_snapshot_roundtrip_image` (put a 1x1 PNG as `public.png`, roundtrip, byte-equal); `test_paste_returns_copied_when_untrusted` (monkeypatch `is_trusted` to False -> "copied" and clipboard holds the text); `test_hold_detector_hold`, `test_hold_detector_double_tap_lock`, `test_hold_detector_escape_cancels`, `test_single_short_tap_still_starts_and_stops`.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement both modules (PyObjC `AppKit.NSPasteboard`, `Quartz.CGEventCreateKeyboardEvent` keycode 9 with `kCGEventFlagMaskCommand`, `Quartz.CGEventTapCreate` on `kCGSessionEventTap`).**
- [ ] **Step 4: Run; expect PASS (the Listener itself is exercised manually in Task 10).**
- [ ] **Step 5: Commit `feat: pasteboard-safe paste and hold-to-talk detector`.**

### Task 8: HUD and the app state machine

**Files:**
- Create: `voz/hud.py`, `voz/app.py`
- Modify: `voz/__main__.py` (`run` subcommand)
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: `hud.Hud()` with `.show(state: str, text: str = "")` (states `listening`, `thinking`, `done`, `copied`, `error`) and `.hide()`, all marshalled to the main thread; `app.Session(engine, recorder, vocab, cfg, paste_fn, hud, history_mod)` with `.on_start()`, `.on_stop()`, `.on_cancel()`, `.fix_last(corrected: str)`; a single worker thread with a FIFO queue so results paste in order; `app.VozApp(rumps.App)` builds the menu (status line, Engine submenu, Fillers on/off, Polish on/off, Open dictionary, Fix last dictation, Launch at login, Quit), starts the hotkey Listener, and on launch calls `paste.request_trust()` when untrusted.

- [ ] **Step 1: Write failing tests** with fakes (engine that sleeps 0.2 s and returns its tag, recorder that returns the fixture, paste that records calls): `test_session_pastes_cleaned_text`, `test_session_skips_silence` (recorder returns zeros -> paste not called, hud shows "error" with "Didn't catch that"), `test_two_quick_dictations_paste_in_order`, `test_cancel_discards`, `test_fix_last_learns_and_updates_history`.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement `hud.py` (borderless `NSPanel`, `NSFloatingWindowLevel`, non-activating, dark rounded pill 360x44 at bottom-centre of the main screen, `NSTextField` label; auto-hide 1.5 s after `done`) and `app.py`.**
- [ ] **Step 4: Run; expect PASS. Then run `.venv/bin/python -m voz run` for 5 s from the shell and confirm it stays up and logs "listener: tap failed (Accessibility not granted)" rather than crashing.**
- [ ] **Step 5: Commit `feat: menu bar app, HUD, dictation session`.**

### Task 9: Optional polish with a local LLM

**Files:**
- Create: `voz/polish.py`
- Modify: `voz/app.py` (call when `cfg.polish`)
- Test: `tests/test_polish.py`

**Interfaces:**
- Produces: `polish.build_prompt(text: str, words: list[str], examples: list[str]) -> str`; `polish.Polisher(model_id="mlx-community/Qwen2.5-1.5B-Instruct-4bit", generate=None)` with `.polish(text, words, examples) -> str` (lazy-loads `mlx_lm` on first call unless a `generate` callable is injected; strips quotes and anything after a blank line; falls back to the input text on any exception or if the output length differs from the input by more than 40%).

- [ ] **Step 1: Write failing tests** with an injected fake `generate`: prompt contains the dictionary words and the examples; fallback on exception; fallback on runaway output.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement; add `mlx-lm` to pyproject optional extra `polish`.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit `feat: optional local LLM polish`.**

### Task 10: Launcher, app bundle, installer, login item

**Files:**
- Create: `launcher/Voz.swift`, `scripts/build_app.sh`, `scripts/install.sh`, `scripts/com.carlosramirez.voz.plist.tpl`, `voz/doctor.py`
- Modify: `voz/__main__.py` (`doctor`)

**Interfaces:**
- `launcher/Voz.swift`: reads `../Resources/python_path` and `../Resources/entry` from the bundle, spawns `Process` with args `["-m","voz","run"]`, forwards SIGTERM, exits with the child's code.
- `scripts/build_app.sh`: `swiftc -O` the launcher into `dist/Voz.app/Contents/MacOS/Voz`, writes `Info.plist` (`CFBundleIdentifier com.carlosramirez.voz`, `LSUIElement true`, `NSMicrophoneUsageDescription`, `CFBundleName Voz`), copies an icon if present, `codesign --force --deep -s - dist/Voz.app`, then `rsync` to `~/Applications/Voz.app`.
- `scripts/install.sh`: creates the venv with uv if missing, installs the package (`uv pip install -e .`), runs `build_app.sh`, writes `~/Library/LaunchAgents/com.carlosramirez.voz.plist` (RunAtLoad, KeepAlive on crash, ProgramArguments = the launcher binary), `launchctl bootout`/`bootstrap`, then prints the two permission steps.
- `voz doctor`: prints Accessibility trusted yes/no, default input device, which models are cached, config path, last 3 history lines.

- [ ] **Step 1: Write `launcher/Voz.swift`, `build_app.sh`, run it; expect `~/Applications/Voz.app` to exist and `codesign -dv` to succeed.**
- [ ] **Step 2: `open ~/Applications/Voz.app`; expect a `python ... -m voz run` child under the Voz process in `ps`, and the menu bar item present (`osascript` is not needed; check `pgrep -f "voz run"`). Quit it with `pkill -f "voz run"`.**
- [ ] **Step 3: Write `install.sh` and the plist template; run it; expect `launchctl print gui/$(id -u)/com.carlosramirez.voz` to show state running.**
- [ ] **Step 4: Implement `voz doctor`; run it; expect a readable report.**
- [ ] **Step 5: Commit `feat: Voz.app launcher, installer, login item, doctor`.**

### Task 11: Seed dictionary, README, brain note

**Files:**
- Modify: `voz/config.py` (`SEED_DICTIONARY`), Create: `README.md`
- Carlos-hq: run `scripts/remember`, append to `brain/decisions.md`, add a TODAY.md loop.

- [ ] **Step 1: Seed list** (from INDEX.md and memory): his business names, the tools he uses daily, his team's first names, and the platforms he posts on. (The public repo ships a neutral list instead.)
- [ ] **Step 2: README** with: what it is, install one-liner, the two permission clicks, hotkey cheatsheet, how to add words, how to fix a dictation, how to switch engine, how to uninstall.
- [ ] **Step 3: `python3 scripts/remember "Voz local dictation app" brand "..."`** from carlos-hq (pillar: brand, since it is Carlos's personal tooling; note repo path, install command, permissions, hotkey). Append decision line to `brain/decisions.md`. Add a TODAY.md loop "Grant Voz Accessibility + test first dictation".
- [ ] **Step 4: Commit in both repos.**
