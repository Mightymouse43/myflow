"""The text prompt panel (Fix last dictation, Add word): a non-activating floating panel that takes typing without
making MyFlow the active app. rumps.Window (an NSAlert) needed the app to activate, and with Chrome in front
holding secure input no activation call worked, so the box could not be typed into (2026-11-18)."""

import AppKit

from voz.prompt import TextPrompt


def test_prompt_submits_the_typed_text_and_closes():
    got = []
    p = TextPrompt(title="Fix last dictation", message="Fix only the misheard words.", default="hello world",
                   ok="Save", on_submit=got.append)
    assert p.panel.styleMask() & AppKit.NSWindowStyleMaskNonactivatingPanel
    assert p.panel.canBecomeKeyWindow()
    p.field.setStringValue_("hello there")
    p._submit_(None)
    assert got == ["hello there"] and not p.panel.isVisible()


def test_prompt_cancel_submits_nothing():
    got = []
    p = TextPrompt(title="Add to dictionary", message="", default="", ok="Add", on_submit=got.append)
    p.field.setStringValue_("typed then cancelled")
    p._cancel_(None)
    assert got == [] and not p.panel.isVisible()


def test_prompt_joins_all_spaces_so_it_shows_over_a_fullscreen_app():
    p = TextPrompt(title="t", message="m", default="", ok="OK", on_submit=lambda s: None)
    assert p.panel.collectionBehavior() & AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
    assert p.panel.level() >= AppKit.NSFloatingWindowLevel
