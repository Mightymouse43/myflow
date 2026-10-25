"""The dictation session (state machine + worker) and the rumps menu bar app around it."""

from __future__ import annotations

import logging
import os
import sys
import queue
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

import numpy as np

from . import config, history, instance, status, textproc
from .audio import is_speech, speech_stats
from .vocab import Vocab

log = logging.getLogger("voz.app")
MIN_SECONDS = 0.5
DIDNT_CATCH = "Didn't catch that"
JOIN_WINDOW_S = 300.0  # a paste this recent, into the same app, most likely landed in the field we are about to use
HOLD_WAIT_S = 60.0  # longest a paste waits for the hotkey to come up when the next dictation is already being held
SLOW_MIC_S = 0.25  # a CoreAudio start/stop slower than this runs inside the key tap's callback: worth a log line


class Session:
    """idle -> listening -> thinking -> paste. Results are processed in order on one worker thread."""

    def __init__(self, engine, recorder, vocab: Vocab, cfg: config.Config, paste_fn: Callable[[str, int], str],
                 hud, frontmost_app: Callable[[], str] | None = None, polisher=None,
                 caret_fn: Callable[[], str | None] | None = None):
        self.engine, self.recorder, self.vocab, self.cfg = engine, recorder, vocab, cfg
        self.paste_fn, self.hud, self.polisher = paste_fn, hud, polisher
        self.frontmost_app = frontmost_app or _frontmost_app_name
        self.caret_fn = caret_fn or (lambda: None)  # paste.char_before_caret in the app; unknown in tests
        self._last_paste: tuple[str, str, float] | None = None  # (app, text, monotonic) of the last real paste
        self._q: queue.Queue = queue.Queue()
        self._pending = 0
        self._cv = threading.Condition()
        self._count = 0
        self._app = ""
        threading.Thread(target=self._worker, name="voz-worker", daemon=True).start()

    # ---- hotkey callbacks (any thread) --------------------------------------
    def on_start(self) -> None:
        if self.recorder.recording:
            return
        try:
            self._app = self.frontmost_app() or ""
        except Exception:
            self._app = ""
        t0 = time.monotonic()
        try:
            self.recorder.start()
        except Exception:
            log.exception("microphone start failed")
            self.hud.show("error", "Microphone not available")
            return
        if time.monotonic() - t0 > SLOW_MIC_S:
            log.warning("microphone took %.2fs to start", time.monotonic() - t0)
        self.hud.show("listening")

    def on_stop(self) -> None:
        if not self.recorder.recording:
            return
        t0 = time.monotonic()
        audio = self.recorder.stop()
        if time.monotonic() - t0 > SLOW_MIC_S:
            log.warning("microphone took %.2fs to stop", time.monotonic() - t0)
        with self._cv:
            self._pending += 1
        self._q.put((audio, self._app))

    def on_cancel(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
            log.info("cancelled while recording (Esc, or another key pressed during the hold)")
        else:
            log.info("cancelled: lone tap, nothing recorded")
        self.hud.hide()

    def fix_last(self, corrected: str) -> list:
        last = history.last()
        if not last:
            return []
        rules = self.vocab.learn(last["final"], corrected.strip())
        history.update_last_final(corrected.strip())
        return rules

    def wait_idle(self, timeout: float) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: self._pending == 0, timeout=timeout)

    # ---- worker ---------------------------------------------------------------
    def _worker(self) -> None:
        while True:
            audio, app = self._q.get()
            try:
                self._process(audio, app)
            except Exception:
                log.exception("dictation failed")
                self.hud.show("error", "Something went wrong (see ~/.voz/voz.log)")
            finally:
                with self._cv:
                    self._pending -= 1
                    self._cv.notify_all()

    def _process(self, audio: np.ndarray, app: str) -> None:
        sr = getattr(self.recorder, "sr", 16000)
        seconds = len(audio) / sr
        if seconds < MIN_SECONDS:
            log.info("dropped: %.2fs hold, too short (under %.1fs)", seconds, MIN_SECONDS)
            self.hud.hide()
            return
        if not is_speech(audio, sr):
            floor, peak = speech_stats(audio, sr)
            log.info("dropped: %.1fs audio, no speech (loud frames %.4f rms, quiet frames %.4f rms)", seconds, peak, floor)
            self.hud.show("error", DIDNT_CATCH)
            return
        self.hud.show("thinking")
        words = self.vocab.words()
        t0 = time.perf_counter()
        raw = self.engine.transcribe(audio, sr, prompt_words=words) or ""
        text = self.vocab.apply(textproc.clean(raw, self.cfg))
        if self.polisher is not None and self.cfg.polish and text.strip():
            text = self.polisher.polish(text, words, [r["final"] for r in history.recent(20)])
        log.info("%.1fs audio -> %.2fs %s: %r", seconds, time.perf_counter() - t0, self.engine.name, text)
        if not text.strip():
            self.hud.show("error", DIDNT_CATCH)
            return
        self._wait_for_hold_release()
        status = self.paste_fn(self._join_prefix(text, app) + text, self.cfg.paste_restore_delay_ms)
        self.hud.show("done" if status == "pasted" else "copied", text)
        self._last_paste = (app, text, time.monotonic()) if status == "pasted" else None
        clip = history.save_clip(audio, sr) if self.cfg.save_clips else None
        history.append(raw, text, app, seconds, clip)
        self._count += 1
        if self._count % 20 == 0:
            history.prune_clips(self.cfg.clip_retention_mb)
        if status == "pasted":
            time.sleep(self.cfg.paste_restore_delay_ms / 1000.0 + 0.05)

    def _wait_for_hold_release(self) -> None:
        """Never paste while the next dictation is being held: the Cmd+V would go out with the hotkey down and,
        read back by the key tap, cancel that hold. The hold rarely outlasts a sentence or two."""
        if not self.recorder.recording:
            return
        t0 = time.monotonic()
        while self.recorder.recording and time.monotonic() - t0 < HOLD_WAIT_S:
            time.sleep(0.02)
        log.info("paste waited %.1fs for the hotkey to come up", time.monotonic() - t0)

    def _join_prefix(self, text: str, app: str) -> str:
        """Space or nothing before the new text. Read the character before the caret when Accessibility lets
        us; otherwise assume a recent paste into the same app is still what sits before the caret."""
        prev, source = None, "caret"
        try:
            prev = self.caret_fn()
        except Exception:
            log.debug("caret read failed", exc_info=True)
        if prev is None and self._last_paste is not None:
            last_app, last_text, at = self._last_paste
            if last_app == app and time.monotonic() - at < JOIN_WINDOW_S:
                prev, source = last_text[-1:], "last paste"
        prefix = textproc.join_prefix(prev, text)
        log.info("join: %r before caret (%s) -> %r", prev, source if prev is not None else "unknown", prefix)
        return prefix


def choose_engines(cfg: config.Config, cached: Callable[[str], bool]) -> list[str]:
    """Engines to try, in order, using only weights already on disk: the configured one first, then the
    other. Loading an uncached engine would download gigabytes inside the app, so that only happens on a
    fresh install when nothing at all is cached."""
    models = {"whisper": cfg.whisper_model, "parakeet": cfg.parakeet_model}
    order = [name for name in (cfg.engine, *[n for n in models if n != cfg.engine]) if cached(models[name])]
    return order or [cfg.engine]


def _frontmost_app_name() -> str:
    import AppKit

    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.localizedName()) if app is not None else ""


# ---- menu bar app ----------------------------------------------------------------

def build_app(cfg: config.Config):
    import rumps
    from PyObjCTools import AppHelper

    from . import launchagent, paste
    from .audio import Recorder
    from .doctor import _model_cached
    from .engines import load_engine
    from .hotkey import KEYCODES, HoldDetector, Listener
    from .hud import Hud
    from .polish import Polisher

    ENGINE_LABELS = {"parakeet": "Parakeet (fast, EN+ES)", "whisper": "Whisper turbo"}
    KEY_LABEL = {"right_option": "Right Option", "right_command": "Right Command", "right_control": "Right Control",
                 "fn": "Globe/Fn", "left_option": "Left Option", "left_control": "Left Control"}
    ASSETS = Path(__file__).resolve().parent / "assets"
    ICONS = {"idle": ASSETS / "menubar-idle.png", "listening": ASSETS / "menubar-listening.png",
             "thinking": ASSETS / "menubar-thinking.png"}

    class IconMirror:
        """Wraps the HUD so the menu bar glyph follows the same states (red = listening, amber = thinking)."""

        def __init__(self, hud, set_icon_state):
            self._hud, self._set = hud, set_icon_state

        def show(self, state, text=""):
            self._hud.show(state, text)
            AppHelper.callAfter(self._set, state if state in ("listening", "thinking") else "idle")

        def hide(self):
            self._hud.hide()
            AppHelper.callAfter(self._set, "idle")

    class MyFlowApp(rumps.App):
        def __init__(self):
            super().__init__("MyFlow", icon=str(ICONS["idle"]), template=True, quit_button=None)
            self.cfg = cfg
            self.status = rumps.MenuItem("Starting…")
            self.status.set_callback(None)
            self.engine_items = {n: rumps.MenuItem(label, callback=self.pick_engine) for n, label in ENGINE_LABELS.items()}
            self._downloading = None
            engine_menu = rumps.MenuItem("Engine")
            for item in self.engine_items.values():
                engine_menu.add(item)
            self.fillers_item = rumps.MenuItem("Remove filler words", callback=self.toggle_fillers)
            self.polish_item = rumps.MenuItem("Polish with local AI", callback=self.toggle_polish)
            self.login_item = rumps.MenuItem("Launch at login", callback=self.toggle_login)
            self.menu = [
                self.status, None, engine_menu, self.fillers_item, self.polish_item, None,
                rumps.MenuItem("Fix last dictation…", callback=self.fix_last),
                rumps.MenuItem("Add word to dictionary…", callback=self.add_word),
                rumps.MenuItem("Open dictionary", callback=self.open_dictionary),
                rumps.MenuItem("Show learned corrections", callback=self.show_learned),
                rumps.MenuItem("Forget learned corrections…", callback=self.forget_learned),
                rumps.MenuItem("Show recent dictations", callback=self.show_history),
                None, self.login_item,
                rumps.MenuItem("Check permissions", callback=self.check_permissions),
                None, rumps.MenuItem("Quit MyFlow", callback=self.quit),
            ]
            self._sync_checks()
            self.hud = IconMirror(Hud(level_fn=self._mic_level), self._set_icon_state)
            self._icon_state = "idle"
            self.vocab = Vocab.load()
            self._dict_mtime = config.DICTIONARY_PATH.stat().st_mtime if config.DICTIONARY_PATH.exists() else 0
            self.engine = None
            self.session = None
            self.listener = None
            self._trusted = False
            self.engine_name = self.cfg.engine
            rumps.Timer(self._boot, 0.2).start()
            rumps.Timer(self._watch_dictionary, 3).start()
            rumps.Timer(self._watch_trust, 5).start()
            rumps.Timer(self._watch_parent, 5).start()

        # ---- startup ----------------------------------------------------
        def _boot(self, timer):
            timer.stop()
            threading.Thread(target=self._load_engine_and_listen, daemon=True).start()

        def _load_first_working_engine(self):
            """Load the configured engine, or the other one if its weights are already on disk."""
            last_error = None
            for name in choose_engines(self.cfg, _model_cached):
                self._set_status("Loading speech model…" if name == self.cfg.engine
                                 else f"{self.cfg.engine} unavailable, loading {name}…")
                try:
                    eng = load_engine(config.Config(**{**self.cfg.__dict__, "engine": name}))
                    eng.load()
                    self.engine_name = name
                    return eng
                except Exception as e:
                    log.exception("engine %s failed to load", name)
                    last_error = e
            self._set_status(f"Speech model failed to load: {last_error}"[:90])
            return None

        def _ready_text(self):
            key = KEY_LABEL.get(self.cfg.hotkey, self.cfg.hotkey)
            note = "" if self.engine_name == self.cfg.engine else f" ({self.engine_name}, fallback)"
            return f"Ready: hold {key} and talk{note}"

        def _load_engine_and_listen(self):
            self.engine = self._load_first_working_engine()
            if self.engine is None:
                return
            polisher = None
            if self.cfg.polish and Polisher.available():
                polisher = Polisher(self.cfg.polish_model)
                threading.Thread(target=self._warm_polisher, args=(polisher,), daemon=True).start()
            self.session = Session(self.engine, Recorder(), self.vocab, self.cfg,
                                   paste.paste_text, self.hud,
                                   polisher=polisher, caret_fn=paste.char_before_caret)
            keycode = KEYCODES.get(self.cfg.hotkey, KEYCODES["right_option"])
            detector = HoldDetector(self.session.on_start, self.session.on_stop, self.session.on_cancel, keycode)
            self.listener = Listener(detector)
            self._trusted = paste.is_trusted()
            if not self._trusted and not os.environ.get("VOZ_SKIP_TRUST_PROMPT"):
                paste.request_trust()
            self._start_listener()

        def _start_listener(self):
            # macOS creates the tap even when untrusted but then delivers nothing, so trust decides the status.
            started = self.listener.start()
            if started and self._trusted:
                self._set_status(self._ready_text())
            else:
                self._set_status("Needs Accessibility: System Settings > Privacy & Security > Accessibility > MyFlow")

        def _watch_trust(self, _):
            if self.listener is None or self._trusted:
                return
            if paste.is_trusted():
                self._trusted = True
                log.info("Accessibility granted; restarting the key listener")
                self.listener.stop()
                self.listener = Listener(self.listener.detector)
                self._start_listener()

        def _set_status(self, text: str):
            AppHelper.callAfter(self._apply_status, text)  # AppKit menu items belong to the main thread
            log.info("status: %s", text)
            try:
                status.write(trusted=self._trusted, engine=self.engine_name, text=text)
            except OSError:
                log.exception("could not write status.json")

        def _apply_status(self, text: str):
            self.status.title = text

        def _mic_level(self) -> float:
            """Latest mic RMS for the HUD's voice bars (0 until the session exists)."""
            session = getattr(self, "session", None)
            return session.recorder.level if session is not None else 0.0

        def _set_icon_state(self, state: str):
            if state == self._icon_state:
                return
            self._icon_state = state
            self.template = state == "idle"  # coloured glyphs must not be recoloured by macOS
            self.icon = str(ICONS[state])

        def _watch_parent(self, _):
            if not instance.parent_alive():
                log.warning("launcher is gone; exiting so launchd can start a fresh MyFlow")
                self.quit(None)

        def _warm_polisher(self, polisher):
            self._set_status("Loading polish model (first time downloads ~1 GB)…")
            try:
                polisher.warm()
                self._set_status(self._ready_text() if self.listener and self._trusted else self.status.title)
            except Exception as e:
                log.exception("polish model failed")
                self._set_status(f"Polish model failed: {e}"[:90])

        def _sync_checks(self):
            for n, item in self.engine_items.items():
                item.state = 1 if self.cfg.engine == n else 0
            self.fillers_item.state = 1 if self.cfg.remove_fillers else 0
            self.polish_item.state = 1 if self.cfg.polish else 0
            self.login_item.state = 1 if launchagent.is_enabled() else 0

        def _watch_dictionary(self, _):
            try:
                m = config.DICTIONARY_PATH.stat().st_mtime
            except OSError:
                return
            if m != self._dict_mtime:
                self._dict_mtime = m
                fresh = Vocab.load()
                self.vocab.rules, self.vocab.learned = fresh.rules, fresh.learned
                log.info("dictionary reloaded (%d words)", len(self.vocab.words()))

        # ---- menu actions ---------------------------------------------------
        def pick_engine(self, sender):
            name = next(n for n, it in self.engine_items.items() if it is sender)
            if name == self.cfg.engine:
                return
            model_id = self.cfg.parakeet_model if name == "parakeet" else self.cfg.whisper_model
            if _model_cached(model_id):
                self._switch_engine(name)
            else:
                self._download_then_switch(name, model_id)

        def _download_then_switch(self, name, model_id):
            """Fetch the weights in a separate process (never inside the app) and switch when they land."""
            item = self.engine_items[name]
            if self._downloading == name:
                rumps.alert(f"{ENGINE_LABELS[name]} is still downloading",
                            "MyFlow switches over by itself the moment it lands.")
                return
            self._downloading = name
            item.title = f"{ENGINE_LABELS[name]} (downloading…)"
            rumps.alert(f"{ENGINE_LABELS[name]} isn't downloaded yet",
                        f"MyFlow is fetching it in the background now (about 2.5 GB; on this connection that can take "
                        f"an hour). Keep dictating with {ENGINE_LABELS[self.cfg.engine]}; the switch happens on its own "
                        f"when the download lands. Progress: ~/.voz/download-{name}.log")
            log_path = config.VOZ_DIR / f"download-{name}.log"

            def run():
                env = {**os.environ, "HF_HUB_DISABLE_XET": "1", "HF_HUB_ENABLE_HF_TRANSFER": "0"}
                code = "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1])"
                try:
                    with open(log_path, "ab") as out:
                        rc = subprocess.call([sys.executable, "-c", code, model_id], env=env, stdout=out, stderr=out)
                except Exception:
                    log.exception("%s download could not start", name)
                    rc = -1
                ok = rc == 0 and _model_cached(model_id)
                self._downloading = None
                AppHelper.callAfter(setattr, item, "title", ENGINE_LABELS[name] if ok else f"{ENGINE_LABELS[name]} (download failed)")
                if ok:
                    log.info("%s downloaded; switching", name)
                    self._switch_engine(name)
                else:
                    log.error("%s download failed (exit %s), see %s", name, rc, log_path)

            threading.Thread(target=run, name=f"voz-download-{name}", daemon=True).start()

        def _switch_engine(self, name):
            self.cfg.engine = name
            config.save(self.cfg)
            AppHelper.callAfter(self._sync_checks)

            def swap():
                if self.session is None:
                    self._load_engine_and_listen()  # boot never finished; do the whole startup now
                    return
                eng = self._load_first_working_engine()
                if eng is None:
                    return
                self.engine = eng
                self.session.engine = eng
                self._set_status(self._ready_text())

            threading.Thread(target=swap, daemon=True).start()

        def toggle_fillers(self, _):
            self.cfg.remove_fillers = not self.cfg.remove_fillers
            config.save(self.cfg)
            self._sync_checks()

        def toggle_polish(self, _):
            if not self.cfg.polish and not Polisher.available():
                rumps.alert("Polish needs one more package",
                            "Run scripts/install.sh again (it installs mlx-lm), then turn Polish on.")
                return
            self.cfg.polish = not self.cfg.polish
            config.save(self.cfg)
            self._sync_checks()
            if self.session:
                if self.cfg.polish:
                    polisher = Polisher(self.cfg.polish_model)
                    self.session.polisher = polisher
                    threading.Thread(target=self._warm_polisher, args=(polisher,), daemon=True).start()
                else:
                    self.session.polisher = None

        def toggle_login(self, _):
            launchagent.set_enabled(not launchagent.is_enabled())
            self._sync_checks()

        def fix_last(self, _):
            last = history.last()
            if not last:
                rumps.alert("MyFlow", "Nothing dictated yet.")
                return
            win = rumps.Window(message="Fix only the words MyFlow misheard. Rewording is not learned, mishearings are.",
                               title="Fix last dictation", default_text=last["final"], ok="Save", cancel="Cancel",
                               dimensions=(420, 120))
            resp = win.run()
            if resp.clicked and self.session:
                rules = self.session.fix_last(resp.text)
                self._set_status(f"Learned {len(rules)} correction(s)" if rules else "Saved. No new rules.")

        def add_word(self, _):
            win = rumps.Window(message="Word or phrase, exactly as it should be typed. Optional: heard form => Word",
                               title="Add to dictionary", default_text="", ok="Add", cancel="Cancel",
                               dimensions=(320, 24))
            resp = win.run()
            if resp.clicked and resp.text.strip():
                line = resp.text.strip()
                with config.DICTIONARY_PATH.open("a") as f:
                    f.write(line + "\n")
                self._watch_dictionary(None)

        def open_dictionary(self, _):
            config.ensure_dirs()
            subprocess.run(["open", "-t", str(config.DICTIONARY_PATH)])

        def show_learned(self, _):
            rules = self.vocab.learned
            body = "\n".join(f"{r.heard}  ->  {r.canonical}" for r in rules) or "Nothing learned yet."
            rumps.alert("Learned corrections", body)

        def forget_learned(self, _):
            if not self.vocab.learned:
                rumps.alert("Learned corrections", "Nothing to forget.")
                return
            if rumps.alert("Forget all learned corrections?", f"{len(self.vocab.learned)} rule(s) will be removed. "
                           "Dictionary words stay.", ok="Forget", cancel="Cancel") == 1:
                self.vocab.forget_learned()
                self._set_status("Learned corrections cleared")

        def show_history(self, _):
            recs = history.recent(10)
            body = "\n".join(f"{r['ts'][11:16]}  {r['final']}" for r in recs) or "Nothing yet."
            rumps.alert("Recent dictations", body)

        def check_permissions(self, _):
            trusted = paste.is_trusted()
            msg = ("Accessibility: granted" if trusted else "Accessibility: NOT granted (needed to paste and to hear the hotkey)")
            msg += "\nMicrophone: macOS asks the first time you hold the key."
            if not trusted:
                paste.request_trust()
            rumps.alert("MyFlow permissions", msg)

        def quit(self, _):
            if self.listener:
                self.listener.stop()
            rumps.quit_application()

    return MyFlowApp()


def run(cfg: config.Config | None = None) -> None:
    import sys

    config.ensure_dirs()
    if not instance.acquire_lock():
        log.warning("another MyFlow is already running; exiting")
        sys.exit(0)
    cfg = cfg or config.load()
    try:
        build_app(cfg).run()
    finally:
        instance.release_lock()
