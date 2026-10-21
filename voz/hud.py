"""A small floating pill just above the Dock: the MyFlow mark with live voice bars while you talk, the text once it lands."""

from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Callable

import AppKit
from PyObjCTools import AppHelper

log = logging.getLogger("voz.hud")

H = 28                                   # pill height; the first version was 46
PAD, ICON, GAP = 12, 16, 10              # side padding, mark size, mark-to-content gap
BARS, BAR_W, BAR_GAP = 5, 3, 3           # the voice bars
COMPACT_W = PAD + ICON + GAP + BARS * BAR_W + (BARS - 1) * BAR_GAP + PAD   # listening / thinking
MIN_W, MAX_W = 120, 300                  # text states grow with the text, within reason
BOTTOM_MARGIN = 24                       # px above the bottom of the visible screen (the Dock)
TICK = 1 / 30
_ICON_PATH = Path(__file__).resolve().parent / "assets" / "menubar-idle.png"

_TINT = {                                # the mark (and the bars) take the state's colour
    "listening": (1.0, 1.0, 1.0),
    "thinking": (0.98, 0.78, 0.20),
    "done": (0.25, 0.85, 0.45),
    "copied": (0.98, 0.78, 0.20),
    "error": (0.60, 0.60, 0.60),
}
_HOLD_SECONDS = {"done": 0.8, "copied": 2.5, "error": 1.8}
_ANIMATED = ("listening", "thinking")
_COMPACT = ("listening", "thinking", "done")   # mark + bars only; done is a short green flash, no text

_WEIGHTS = (0.55, 0.80, 1.00, 0.80, 0.55)    # centre bar tallest
_DECAY = (0.80, 0.72, 0.60, 0.72, 0.80)      # per tick; outer bars linger a touch so they do not move in lockstep
_ATTACK = 0.45


def level_to_unit(rms: float) -> float:
    """Mic RMS (float32 scale) to 0..1: the speech gate (-50 dB) is 0, loud speech (-16 dB) is 1."""
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(rms)
    return min(1.0, max(0.0, (db + 50) / 34))


class Meter:
    """Turns a stream of mic levels into five bar heights with a fast attack and a soft decay."""

    def __init__(self, min_h: float = 3.0, max_h: float = 18.0):
        self.min_h, self.max_h = min_h, max_h
        self._s = [0.0] * BARS

    def reset(self) -> None:
        self._s = [0.0] * BARS

    def update(self, rms: float) -> list[float]:
        u = level_to_unit(rms)
        for i, s in enumerate(self._s):
            self._s[i] = s + (u - s) * _ATTACK if u > s else s * _DECAY[i]
        span = self.max_h - self.min_h
        return [self.min_h + span * _WEIGHTS[i] * self._s[i] for i in range(BARS)]

    def idle(self, t: float) -> list[float]:
        """A slow wave for the thinking state."""
        span = self.max_h - self.min_h
        return [self.min_h + span * 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.9 * t + i * 0.9)) for i in range(BARS)]


def shown_text(state: str, text: str) -> str:
    """What the pill says: nothing for the compact states, a short note for a blocked paste, the message for errors."""
    if state in _COMPACT:
        return ""
    if state == "copied":
        return "Copied, paste blocked"
    return text.replace("\n", " ")


def pill_width(state: str, text_px: float) -> float:
    if state in _COMPACT:
        return float(COMPACT_W)
    return float(min(MAX_W, max(MIN_W, PAD + ICON + GAP + text_px + PAD)))


def pill_origin(visible, width: float) -> tuple[float, float]:
    """Centred horizontally, BOTTOM_MARGIN above the bottom of the screen's visible frame."""
    (ox, oy), (w, _h) = visible
    return (ox + (w - width) / 2, oy + BOTTOM_MARGIN)


def anchor_point(window_bounds, primary_height: float, mouse) -> tuple[float, float]:
    """Where the pill should look for its screen: the centre of the window being dictated into, else the mouse.

    window_bounds is (x, y, w, h) in CoreGraphics coordinates (origin top-left of the main screen, y down);
    the result is in AppKit coordinates (origin bottom-left of the main screen, y up).
    """
    if window_bounds is None:
        return (float(mouse[0]), float(mouse[1]))
    x, y, w, h = window_bounds
    return (x + w / 2, primary_height - (y + h / 2))


def front_window_bounds_from(windows, pid: int):
    """Bounds (x, y, w, h) of the first real window owned by pid in a front-to-back CGWindowList.

    Skips overlays (layer != 0), invisible windows (alpha 0) and specks under 50 px: Electron apps keep
    an alpha-0 title strip in front of their actual window, parked off the top of the screen.
    """
    for w in windows:
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer", 0) != 0:
            continue
        if float(w.get("kCGWindowAlpha", 1.0)) <= 0.0:
            continue
        b = w.get("kCGWindowBounds") or {}
        try:
            x, y, wd, ht = float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
        except (KeyError, TypeError, ValueError):
            continue
        if wd < 50 or ht < 50:
            continue
        return (x, y, wd, ht)
    return None


def _front_window_bounds():
    """CoreGraphics bounds of the frontmost app's real top window, or None. Needs no extra permission."""
    try:
        import Quartz

        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []   # front to back
        return front_window_bounds_from(windows, app.processIdentifier())
    except Exception:
        log.debug("front window lookup failed", exc_info=True)
    return None


def pick_screen(point, frames) -> int:
    """Index of the screen frame holding the point (the one you are working on), else the nearest screen."""
    px, py = point
    best, best_d = 0, None
    for i, ((ox, oy), (w, h)) in enumerate(frames):
        if ox <= px < ox + w and oy <= py < oy + h:
            return i
        dx = max(ox - px, 0.0, px - (ox + w))
        dy = max(oy - py, 0.0, py - (oy + h))
        d = dx * dx + dy * dy
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


class Hud:
    def __init__(self, level_fn: Callable[[], float] | None = None):
        self._level_fn = level_fn or (lambda: 0.0)
        self._panel = None
        self._icon = None
        self._label = None
        self._bars: list = []
        self._meter = Meter()
        self._hold: threading.Timer | None = None
        self._anim = None
        self._state = ""
        self._t0 = 0.0

    # ---- public, callable from any thread ---------------------------------
    def show(self, state: str, text: str = "") -> None:
        AppHelper.callAfter(self._show, state, text)

    def hide(self) -> None:
        AppHelper.callAfter(self._hide)

    # ---- main thread only ---------------------------------------------------
    def _ensure(self) -> None:
        if self._panel is not None:
            return
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (COMPACT_W, H)), style, AppKit.NSBackingStoreBuffered, False)
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary)

        content = AppKit.NSView.alloc().initWithFrame_(((0, 0), (COMPACT_W, H)))
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(H / 2)
        content.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.09, 0.94).CGColor())

        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(_ICON_PATH))
        if image is not None:
            image.setTemplate_(True)
        icon = AppKit.NSImageView.alloc().initWithFrame_(((PAD, (H - ICON) / 2), (ICON, ICON)))
        icon.setImage_(image)
        icon.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
        content.addSubview_(icon)

        bars = []
        x = PAD + ICON + GAP
        for _ in range(BARS):
            bar = AppKit.NSView.alloc().initWithFrame_(((x, (H - self._meter.min_h) / 2), (BAR_W, self._meter.min_h)))
            bar.setWantsLayer_(True)
            bar.layer().setCornerRadius_(BAR_W / 2)
            content.addSubview_(bar)
            bars.append(bar)
            x += BAR_W + BAR_GAP

        label = AppKit.NSTextField.labelWithString_("")
        label.setFrame_(((PAD + ICON + GAP, 0), (MAX_W - PAD - ICON - GAP - PAD, H)))
        label.setTextColor_(AppKit.NSColor.whiteColor())
        label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(12, AppKit.NSFontWeightMedium))
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        label.setMaximumNumberOfLines_(1)
        label.setAlignment_(AppKit.NSTextAlignmentLeft)
        cell = label.cell()
        if cell is not None:
            cell.setUsesSingleLineMode_(True)
        content.addSubview_(label)

        panel.setContentView_(content)
        self._panel, self._icon, self._label, self._bars = panel, icon, label, bars

    def _show(self, state: str, text: str) -> None:
        self._ensure()
        self._cancel_hold()
        r, g, b = _TINT.get(state, _TINT["error"])
        colour = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1)
        self._icon.setContentTintColor_(colour)
        animated, compact = state in _ANIMATED, state in _COMPACT
        shown = shown_text(state, text)
        self._label.setStringValue_(shown)
        self._label.setHidden_(compact)
        for bar in self._bars:
            bar.setHidden_(not compact)
            bar.layer().setBackgroundColor_(colour.CGColor())
        text_px = self._label.attributedStringValue().size().width if shown else 0.0
        self._place(pill_width(state, text_px))
        self._state, self._t0 = state, time.monotonic()
        if animated:
            if state == "listening":
                self._meter.reset()
            self._start_anim()
        else:
            self._stop_anim()
        self._panel.orderFrontRegardless()
        hold = _HOLD_SECONDS.get(state)
        if hold:
            self._hold = threading.Timer(hold, self.hide)
            self._hold.daemon = True
            self._hold.start()

    def _place(self, width: float) -> None:
        """Size the pill and park it bottom-centre on the screen holding the window you dictate into."""
        screens = AppKit.NSScreen.screens() or [AppKit.NSScreen.mainScreen()]
        rect = lambda f: ((f.origin.x, f.origin.y), (f.size.width, f.size.height))
        frames = [rect(s.frame()) for s in screens]            # whole screens, so the menu bar strip counts
        visibles = [rect(s.visibleFrame()) for s in screens]   # minus menu bar and Dock, for placement
        p = AppKit.NSEvent.mouseLocation()
        anchor = anchor_point(_front_window_bounds(), frames[0][1][1], (p.x, p.y))
        x, y = pill_origin(visibles[pick_screen(anchor, frames)], width)
        self._panel.setFrame_display_(((x, y), (width, H)), True)
        self._label.setFrame_(((PAD + ICON + GAP, 0), (max(0.0, width - PAD - ICON - GAP - PAD), H)))

    def _start_anim(self) -> None:
        if self._anim is not None:
            return
        timer = AppKit.NSTimer.timerWithTimeInterval_repeats_block_(TICK, True, self._tick)
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(timer, AppKit.NSRunLoopCommonModes)
        self._anim = timer

    def _stop_anim(self) -> None:
        if self._anim is not None:
            self._anim.invalidate()
            self._anim = None

    def _tick(self, _timer=None) -> None:
        if self._state == "listening":
            try:
                level = float(self._level_fn() or 0.0)
            except Exception:
                level = 0.0
            heights = self._meter.update(level)
        elif self._state == "thinking":
            heights = self._meter.idle(time.monotonic() - self._t0)
        else:
            self._stop_anim()
            return
        for bar, h in zip(self._bars, heights):
            bar.setFrame_(((bar.frame().origin.x, (H - h) / 2), (BAR_W, h)))

    def _cancel_hold(self) -> None:
        if self._hold:
            self._hold.cancel()
            self._hold = None

    def _hide(self) -> None:
        self._cancel_hold()
        self._stop_anim()
        self._state = ""
        if self._panel is not None:
            self._panel.orderOut_(None)
