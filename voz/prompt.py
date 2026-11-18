"""A small text prompt (Fix last dictation, Add word) that takes typing without making MyFlow the active app.

rumps.Window is an NSAlert: it only takes keystrokes once the app is active, and a menu bar app with no Dock
presence cannot always activate itself (with Chrome in front holding secure keyboard input, no activation call
worked, 2026-11-18). A non-activating floating panel can become the key window on its own, like Spotlight.
"""

from __future__ import annotations

from typing import Callable

import AppKit
import objc

W, H, PAD = 460, 168, 16


class _Panel(AppKit.NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False

    def cancelOperation_(self, sender):  # Esc
        owner = getattr(self, "_owner", None)
        if owner is not None:
            owner._cancel_(sender)


class _Actions(AppKit.NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Actions, self).init()
        self._owner = owner
        return self

    def submit_(self, sender):
        self._owner._submit_(sender)

    def cancel_(self, sender):
        self._owner._cancel_(sender)


class TextPrompt:
    """Build once, show(); on_submit gets the text when the user presses Enter or the OK button; Esc/Cancel closes."""

    def __init__(self, title: str, message: str, default: str, ok: str, on_submit: Callable[[str], None],
                 cancel: str = "Cancel"):
        AppKit.NSApplication.sharedApplication()
        self.on_submit = on_submit
        self._actions = _Actions.alloc().initWithOwner_(self)
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskNonactivatingPanel
                 | AppKit.NSWindowStyleMaskUtilityWindow)
        panel = _Panel.alloc().initWithContentRect_styleMask_backing_defer_(((0, 0), (W, H)), style,
                                                                              AppKit.NSBackingStoreBuffered, False)
        panel._owner = self
        panel.setTitle_(title)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setHidesOnDeactivate_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                     | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        content = panel.contentView()

        note = AppKit.NSTextField.wrappingLabelWithString_(message)
        note.setFrame_(((PAD, H - PAD - 34), (W - 2 * PAD, 34)))
        note.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        note.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        content.addSubview_(note)

        field = AppKit.NSTextField.alloc().initWithFrame_(((PAD, H - PAD - 34 - 8 - 28), (W - 2 * PAD, 28)))
        field.setStringValue_(default)
        field.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        field.setTarget_(self._actions)
        field.setAction_("submit:")
        content.addSubview_(field)

        def button(label, action, key, x):
            b = AppKit.NSButton.buttonWithTitle_target_action_(label, self._actions, action)
            b.setBezelStyle_(AppKit.NSBezelStyleRounded)
            b.setKeyEquivalent_(key)
            b.setFrame_(((x, PAD - 4), (96, 32)))
            content.addSubview_(b)
            return b

        button(cancel, "cancel:", "\x1b", W - PAD - 96 - 8 - 96)
        button(ok, "submit:", "\r", W - PAD - 96)
        self.panel, self.field = panel, field

    def show(self) -> None:
        self.panel.center()
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.field)
        self.field.selectText_(None)

    def _submit_(self, _sender) -> None:
        text = str(self.field.stringValue())
        self.panel.orderOut_(None)
        self.on_submit(text)

    def _cancel_(self, _sender) -> None:
        self.panel.orderOut_(None)
