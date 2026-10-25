"""Clipboard-safe text injection: save the pasteboard, paste with Cmd+V, put it back."""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Literal

import AppKit
import Quartz
import ApplicationServices as AX
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

from .hotkey import OWN_EVENT_TAG

log = logging.getLogger("voz.paste")

Snapshot = list[list[tuple[str, bytes]]]  # one inner list per pasteboard item
KEY_V = 9  # ANSI keyboard layout
# cmd (54/55), option (58/61), control (59/62), shift (56/60), fn (63)
MODIFIER_KEYCODES = (54, 55, 58, 61, 59, 62, 56, 60, 63)
MODIFIER_WAIT_S = 1.5  # how long to wait for the user to let go of the hotkey before Cmd+V
AX_TIMEOUT_S = 0.3  # a frozen front app must not hold the paste hostage (the AX default is 6 s)
_carbon = None


def is_trusted() -> bool:
    return bool(AXIsProcessTrusted())


def request_trust() -> bool:
    """Ask macOS to list MyFlow under Accessibility (opens System Settings the first time)."""
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))


def secure_input_enabled() -> bool:
    """True while a password field (or Terminal secure input) owns the keyboard; synthetic Cmd+V is dropped then."""
    global _carbon
    try:
        if _carbon is None:
            _carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
            _carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        return bool(_carbon.IsSecureEventInputEnabled())
    except Exception:  # pragma: no cover
        log.exception("secure input probe failed")
        return False


def _modifier_held() -> bool:
    try:
        state = Quartz.kCGEventSourceStateCombinedSessionState
        return any(Quartz.CGEventSourceKeyState(state, k) for k in MODIFIER_KEYCODES)
    except Exception:  # pragma: no cover
        return False


def _wait_for_modifiers_release() -> None:
    """The hotkey is a modifier; Cmd+V posted while it is still down becomes Cmd+Option+V."""
    deadline = time.monotonic() + MODIFIER_WAIT_S
    while _modifier_held() and time.monotonic() < deadline:
        time.sleep(0.02)


def _pb() -> AppKit.NSPasteboard:
    return AppKit.NSPasteboard.generalPasteboard()


def snapshot_pasteboard() -> Snapshot:
    snap: Snapshot = []
    for item in _pb().pasteboardItems() or []:
        entry = []
        for t in item.types() or []:
            data = item.dataForType_(t)
            if data is not None:
                entry.append((str(t), bytes(data)))
        if entry:
            snap.append(entry)
    return snap


def restore_pasteboard(snap: Snapshot) -> None:
    pb = _pb()
    pb.clearContents()
    if not snap:
        return
    items = []
    for entry in snap:
        item = AppKit.NSPasteboardItem.alloc().init()
        for t, b in entry:
            item.setData_forType_(AppKit.NSData.dataWithBytes_length_(b, len(b)), t)
        items.append(item)
    pb.writeObjects_(items)


def _send_cmd_v() -> bool:
    try:
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        Quartz.CGEventSourceSetUserData(src, OWN_EVENT_TAG)
        down = Quartz.CGEventCreateKeyboardEvent(src, KEY_V, True)
        up = Quartz.CGEventCreateKeyboardEvent(src, KEY_V, False)
        for ev in (down, up):
            Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGEventSourceUserData, OWN_EVENT_TAG)  # hotkey.py skips these
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        return True
    except Exception:  # pragma: no cover - defensive, Quartz rarely raises
        log.exception("posting Cmd+V failed")
        return False


def paste_text(text: str, restore_delay_ms: int = 400) -> Literal["pasted", "copied"]:
    """Put text at the cursor. Falls back to leaving it on the clipboard when pasting is impossible."""
    snap = snapshot_pasteboard()
    pb = _pb()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    if not is_trusted():
        log.warning("Accessibility not granted; text left on the clipboard")
        return "copied"
    if secure_input_enabled():
        log.info("secure input active; text left on the clipboard")
        return "copied"
    _wait_for_modifiers_release()
    if not _send_cmd_v():
        return "copied"
    threading.Timer(max(restore_delay_ms, 50) / 1000.0, restore_pasteboard, args=(snap,)).start()
    return "pasted"


class _SystemAX:
    """The Accessibility reads behind char_before_caret, kept together so tests can stand in for them."""

    def __init__(self):
        self._sys = AX.AXUIElementCreateSystemWide()
        try:
            AX.AXUIElementSetMessagingTimeout(self._sys, AX_TIMEOUT_S)
        except Exception:  # pragma: no cover - older PyObjC without the binding
            pass

    @staticmethod
    def _get(el, attr):
        err, value = AX.AXUIElementCopyAttributeValue(el, attr, None)
        return value if err == AX.kAXErrorSuccess else None

    def focused_element(self):
        return self._get(self._sys, AX.kAXFocusedUIElementAttribute)

    def selected_range(self, el):
        value = self._get(el, AX.kAXSelectedTextRangeAttribute)
        if value is None:
            return None
        ok, rng = AX.AXValueGetValue(value, AX.kAXValueCFRangeType, None)
        if not ok:
            return None
        loc = getattr(rng, "location", None)
        return (int(rng[0]), int(rng[1])) if loc is None else (int(loc), int(rng.length))

    def string_for_range(self, el, loc, length):
        rng = AX.AXValueCreate(AX.kAXValueCFRangeType, (loc, length))
        err, s = AX.AXUIElementCopyParameterizedAttributeValue(el, AX.kAXStringForRangeParameterizedAttribute, rng, None)
        return str(s) if err == AX.kAXErrorSuccess and s is not None else None

    def text_value(self, el):
        value = self._get(el, AX.kAXValueAttribute)
        return str(value) if isinstance(value, str) else None


def char_before_caret(ax=None) -> str | None:
    """The character just before the caret in the focused text field.

    "" at the start of a field, None when it cannot be read: not trusted, nothing text-like has focus, or the
    front app does not expose its text to Accessibility (some web views). Callers fall back to a guess then."""
    if not is_trusted():
        return None
    try:
        ax = ax or _SystemAX()
        el = ax.focused_element()
        if el is None:
            return None
        rng = ax.selected_range(el)
        if rng is None:
            return None
        loc = int(rng[0])  # a selection is replaced by the paste, so what matters is what precedes its start
        if loc <= 0:
            return ""
        s = ax.string_for_range(el, loc - 1, 1)
        if not s:
            value = ax.text_value(el)
            if value is None or loc > len(value):
                return None
            s = value[loc - 1]
        return s[-1]
    except Exception:
        log.debug("caret probe failed", exc_info=True)
        return None
