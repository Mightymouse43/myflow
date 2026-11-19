import base64
import time

import AppKit
import pytest

from voz import paste

PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _pb():
    return AppKit.NSPasteboard.generalPasteboard()


@pytest.fixture(autouse=True)
def keep_users_clipboard():
    """Tests touch the real clipboard; put back whatever Carlos had on it."""
    before = _pb().stringForType_(AppKit.NSPasteboardTypeString)
    yield
    _pb().clearContents()
    if before is not None:
        _pb().setString_forType_(before, AppKit.NSPasteboardTypeString)


def test_pasteboard_snapshot_roundtrip_text():
    _pb().clearContents()
    _pb().setString_forType_("before", AppKit.NSPasteboardTypeString)
    snap = paste.snapshot_pasteboard()
    _pb().clearContents()
    _pb().setString_forType_("x", AppKit.NSPasteboardTypeString)
    paste.restore_pasteboard(snap)
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) == "before"


def test_pasteboard_snapshot_roundtrip_image():
    _pb().clearContents()
    data = AppKit.NSData.dataWithBytes_length_(PNG_1x1, len(PNG_1x1))
    _pb().setData_forType_(data, "public.png")
    snap = paste.snapshot_pasteboard()
    _pb().clearContents()
    _pb().setString_forType_("x", AppKit.NSPasteboardTypeString)
    paste.restore_pasteboard(snap)
    assert bytes(_pb().dataForType_("public.png")) == PNG_1x1
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) is None


def test_restore_empty_snapshot_clears():
    _pb().clearContents()
    snap = paste.snapshot_pasteboard()
    _pb().setString_forType_("x", AppKit.NSPasteboardTypeString)
    paste.restore_pasteboard(snap)
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) is None


def test_paste_returns_copied_when_untrusted(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: False)
    assert paste.paste_text("hello voz", restore_delay_ms=10) == "copied"
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) == "hello voz"


def test_paste_pasted_path_restores_clipboard(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    monkeypatch.setattr(paste, "secure_input_enabled", lambda: False)
    sent = []
    monkeypatch.setattr(paste, "_send_cmd_v", lambda: sent.append(1) or True)
    _pb().clearContents()
    _pb().setString_forType_("keep me", AppKit.NSPasteboardTypeString)
    assert paste.paste_text("new text", restore_delay_ms=50) == "pasted"
    assert sent == [1]
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) == "new text"
    time.sleep(0.4)
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) == "keep me"


def test_paste_falls_back_to_copied_when_event_post_fails(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    monkeypatch.setattr(paste, "_send_cmd_v", lambda: False)
    assert paste.paste_text("plan b", restore_delay_ms=10) == "copied"
    time.sleep(0.1)
    assert _pb().stringForType_(AppKit.NSPasteboardTypeString) == "plan b"


def test_paste_waits_for_modifiers_to_release(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    monkeypatch.setattr(paste, "secure_input_enabled", lambda: False)
    calls = {"held": 0}
    order = []

    def held():
        calls["held"] += 1
        order.append("check")
        return calls["held"] <= 3

    monkeypatch.setattr(paste, "_modifier_held", held)
    monkeypatch.setattr(paste, "_send_cmd_v", lambda: order.append("send") or True)
    assert paste.paste_text("after release", restore_delay_ms=10) == "pasted"
    assert calls["held"] >= 4 and order[-1] == "send"


def test_paste_gives_up_waiting_for_modifiers(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    monkeypatch.setattr(paste, "secure_input_enabled", lambda: False)
    monkeypatch.setattr(paste, "_modifier_held", lambda: True)
    monkeypatch.setattr(paste, "MODIFIER_WAIT_S", 0.15)
    sent = []
    monkeypatch.setattr(paste, "_send_cmd_v", lambda: sent.append(1) or True)
    t0 = time.monotonic()
    assert paste.paste_text("eventually", restore_delay_ms=10) == "pasted"
    assert sent == [1] and 0.1 <= time.monotonic() - t0 < 1.0


def test_secure_input_probe_runs():
    assert paste.secure_input_enabled() in (True, False)


def test_modifier_probe_runs():
    assert paste._modifier_held() in (True, False)


# ---- reading the character before the caret through Accessibility ----

class _FakeAX:
    """Stand-in for the three AX calls paste makes; the real ones need a trusted process."""

    def __init__(self, focused=True, selection=(5, 0), value=None):
        self.focused, self.selection, self.value = focused, selection, value
        self.string_for_range_value = None
        self.ranges_asked = []

    def focused_element(self):
        return object() if self.focused else None

    def selected_range(self, el):
        return self.selection

    def string_for_range(self, el, loc, length):
        self.ranges_asked.append((loc, length))
        return self.string_for_range_value

    def text_value(self, el):
        return self.value


def _ax(**kw):
    string_for_range = kw.pop("string_for_range", None)
    ax = _FakeAX(**kw)
    ax.string_for_range_value = string_for_range
    return ax


def test_char_before_caret_reads_one_character_through_string_for_range(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    ax = _ax(selection=(12, 0), string_for_range=".")
    assert paste.char_before_caret(ax=ax) == "."
    assert ax.ranges_asked == [(11, 1)]


def test_char_before_caret_is_empty_at_the_start_of_a_field(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    assert paste.char_before_caret(ax=_ax(selection=(0, 0))) == ""


def test_char_before_caret_falls_back_to_the_whole_value(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    assert paste.char_before_caret(ax=_ax(selection=(5, 0), string_for_range=None, value="Hello world")) == "o"


def test_char_before_caret_uses_the_start_of_a_selection(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    assert paste.char_before_caret(ax=_ax(selection=(6, 5), value="Hello world")) == " "


def test_char_before_caret_is_unknown_without_a_focused_text_element(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    assert paste.char_before_caret(ax=_ax(focused=False)) is None
    assert paste.char_before_caret(ax=_ax(selection=None)) is None


def test_char_before_caret_is_unknown_when_untrusted(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: False)
    assert paste.char_before_caret(ax=_ax(string_for_range=".")) is None


def test_char_before_caret_real_probe_never_raises():
    out = paste.char_before_caret()
    assert out is None or (isinstance(out, str) and len(out) <= 1)


def test_cmd_v_events_carry_the_apps_own_tag(monkeypatch):
    """So the hotkey tap can tell MyFlow's paste from a key the user pressed."""
    import Quartz
    from voz.hotkey import OWN_EVENT_TAG
    posted = []
    monkeypatch.setattr(paste.Quartz, "CGEventPost", lambda tap, ev: posted.append(ev))
    assert paste._send_cmd_v() is True
    assert len(posted) == 2
    assert all(Quartz.CGEventGetIntegerValueField(ev, Quartz.kCGEventSourceUserData) == OWN_EVENT_TAG for ev in posted)


# ---- secure keyboard input never blocks the paste (2026-11-18) ---------------------------------------------
# Chrome kept a password field's secure-input grant for a whole day. A gate that refused to paste into the holder
# sent every Chrome paste to the clipboard; the same synthetic Cmd+V pasted fine the moment it was attempted.
# Secure input hides keystrokes from other processes, it does not drop posted ones. The holder is only logged.

def _secure(monkeypatch, enabled, holder, front, send):
    monkeypatch.setattr(paste, "is_trusted", lambda: True)
    monkeypatch.setattr(paste, "secure_input_enabled", lambda: enabled)
    monkeypatch.setattr(paste, "secure_input_holder", lambda: holder)
    monkeypatch.setattr(paste, "_frontmost", lambda: front)
    monkeypatch.setattr(paste, "_modifier_held", lambda: False)
    monkeypatch.setattr(paste, "_send_cmd_v", lambda: send.append(1) or True)


def test_secure_input_held_by_another_app_does_not_block_the_paste(monkeypatch):
    sent = []
    _secure(monkeypatch, True, (664, "Google Chrome"), (9000, "Claude"), sent)
    assert paste.paste_text("hello", restore_delay_ms=10) == "pasted" and sent == [1]


def test_secure_input_held_by_the_front_app_still_pastes(monkeypatch, caplog):
    sent = []
    _secure(monkeypatch, True, (664, "Google Chrome"), (664, "Google Chrome"), sent)
    with caplog.at_level("INFO", logger="voz.paste"):
        assert paste.paste_text("hello", restore_delay_ms=10) == "pasted" and sent == [1]
    assert paste.why_copied() == ""
    assert "Google Chrome" in caplog.text and "pasting anyway" in caplog.text


def test_secure_input_with_an_unknown_holder_still_pastes(monkeypatch):
    sent = []
    _secure(monkeypatch, True, None, (9000, "Claude"), sent)
    assert paste.paste_text("hello", restore_delay_ms=10) == "pasted" and sent == [1]


def test_why_copied_names_missing_accessibility(monkeypatch):
    monkeypatch.setattr(paste, "is_trusted", lambda: False)
    assert paste.paste_text("hello", restore_delay_ms=10) == "copied"
    assert "Accessibility" in paste.why_copied()


def test_secure_input_holder_probe_runs():
    h = paste.secure_input_holder()
    assert h is None or (isinstance(h[0], int) and isinstance(h[1], str))
