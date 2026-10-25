"""Hold-to-talk key detection: a pure state machine plus a Quartz event tap that feeds it."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("voz.hotkey")

KEYCODES = {"right_option": 61, "right_command": 54, "right_control": 62, "fn": 63,
            "left_option": 58, "left_control": 59}
ESC_KEYCODE = 53
OWN_EVENT_TAG = 0x4D59464C  # "MYFL": stamped on the Cmd+V MyFlow posts (paste.py) so the tap never reads it as a chord

# Which modifier flag a given modifier keycode toggles in a flagsChanged event.
_FLAG_FOR_KEYCODE = {
    61: 1 << 19,  # kCGEventFlagMaskAlternate
    58: 1 << 19,
    54: 1 << 20,  # kCGEventFlagMaskCommand
    62: 1 << 18,  # kCGEventFlagMaskControl
    59: 1 << 18,
    63: 1 << 23,  # kCGEventFlagMaskSecondaryFn
}


class HoldDetector:
    """Hold = dictate while held. Quick double tap = lock on until the next tap. Esc = cancel.

    A lone quick tap (under tap_ms, no second tap) is cancelled, and any other key pressed while the
    hotkey is held cancels too, so Option+e style chords never dictate."""

    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None],
                 on_cancel: Callable[[], None], keycode: int, tap_ms: int = 250, double_tap_ms: int = 350):
        self.on_start, self.on_stop, self.on_cancel = on_start, on_stop, on_cancel
        self.keycode = keycode
        self.tap_s = tap_ms / 1000.0
        self.double_tap_s = double_tap_ms / 1000.0
        self.state = "idle"  # idle | held | tap_wait | locked
        self._down_at = 0.0
        self._stop_at = 0.0
        self._lock = threading.Lock()

    @property
    def locked(self) -> bool:
        return self.state == "locked"

    @property
    def active(self) -> bool:
        return self.state != "idle"

    def feed(self, keycode: int, down: bool, now: float) -> None:
        with self._lock:
            if keycode == ESC_KEYCODE:
                if down and self.state != "idle":
                    self.state = "idle"
                    self.on_cancel()
                return
            if keycode != self.keycode:
                # Any ordinary key pressed while the hotkey is held is a shortcut chord
                # (Option+e for an accent, Option+arrow), not a dictation: discard it.
                if down and self.state in ("held", "tap_wait"):
                    self.state = "idle"
                    self.on_cancel()
                return
            if down:
                if self.state == "idle":
                    self.state = "held"
                    self._down_at = now
                    self.on_start()
                elif self.state == "tap_wait":
                    self.state = "locked"
                elif self.state == "locked":
                    self.state = "idle"
                    self.on_stop()
            else:
                if self.state == "held":
                    if now - self._down_at < self.tap_s:
                        self.state = "tap_wait"
                        self._stop_at = now + self.double_tap_s
                    else:
                        self.state = "idle"
                        self.on_stop()

    def tick(self, now: float) -> None:
        with self._lock:
            if self.state == "tap_wait" and now >= self._stop_at:
                # A lone quick tap is an accident or an abandoned double tap: nothing worth transcribing.
                self.state = "idle"
                self.on_cancel()


class Listener:
    """Runs a listen-only CGEventTap on its own thread and feeds the detector."""

    def __init__(self, detector: HoldDetector):
        self.detector = detector
        self._thread: threading.Thread | None = None
        self._tap = None
        self._loop = None
        self.error: str | None = None

    def _callback(self, proxy, type_, event, refcon):
        import Quartz

        if type_ in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData) == OWN_EVENT_TAG:
            return event  # our own paste on its way to the front app, not a key the user pressed
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        now = time.monotonic()
        if type_ == Quartz.kCGEventFlagsChanged:
            flag = _FLAG_FOR_KEYCODE.get(keycode)
            if flag is not None:
                down = bool(Quartz.CGEventGetFlags(event) & flag)
                self.detector.feed(keycode, down, now)
        elif type_ == Quartz.kCGEventKeyDown:
            self.detector.feed(keycode, True, now)  # Esc cancels; other keys cancel while held
        return event

    def _run(self, ready: threading.Event) -> None:
        import Quartz

        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap, Quartz.kCGEventTapOptionListenOnly,
            mask, self._callback, None)
        if not self._tap:
            self.error = "could not create the key listener (grant Accessibility to MyFlow, then restart it)"
            ready.set()
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
        timer = Quartz.CFRunLoopTimerCreate(None, Quartz.CFAbsoluteTimeGetCurrent() + 0.05, 0.05, 0, 0,
                                            lambda t, info: self.detector.tick(time.monotonic()), None)
        Quartz.CFRunLoopAddTimer(self._loop, timer, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        ready.set()
        Quartz.CFRunLoopRun()

    def start(self) -> bool:
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="voz-hotkey", daemon=True)
        self._thread.start()
        ready.wait(timeout=5.0)
        if self.error:
            log.warning("listener: %s", self.error)
            return False
        return True

    def stop(self) -> None:
        import Quartz

        if self._loop is not None:
            Quartz.CFRunLoopStop(self._loop)
