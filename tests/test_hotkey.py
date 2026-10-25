from voz.hotkey import ESC_KEYCODE, KEYCODES, HoldDetector


def mk(**kw):
    ev: list[str] = []
    d = HoldDetector(on_start=lambda: ev.append("start"), on_stop=lambda: ev.append("stop"),
                     on_cancel=lambda: ev.append("cancel"), keycode=KEYCODES["right_option"], **kw)
    return d, ev


def test_keycodes_cover_the_configurable_keys():
    assert set(KEYCODES) >= {"right_option", "right_command", "right_control", "fn"}
    assert KEYCODES["right_option"] == 61 and ESC_KEYCODE == 53


def test_hold_detector_hold():
    d, ev = mk()
    d.feed(61, True, 0.0)
    d.feed(61, False, 1.0)
    assert ev == ["start", "stop"]


def test_single_short_tap_is_cancelled_after_the_window():
    d, ev = mk(tap_ms=250, double_tap_ms=350)
    d.feed(61, True, 0.0)
    d.feed(61, False, 0.1)
    d.tick(0.3)
    assert ev == ["start"]
    d.tick(0.5)
    assert ev == ["start", "cancel"] and not d.active


def test_other_key_while_held_cancels():
    d, ev = mk()
    d.feed(61, True, 0.0)
    d.feed(14, True, 0.1)  # Option+e: an accent, not a dictation
    assert ev == ["start", "cancel"]
    d.feed(61, False, 0.5)
    assert ev == ["start", "cancel"]


def test_other_key_in_tap_wait_cancels():
    d, ev = mk(tap_ms=250, double_tap_ms=350)
    d.feed(61, True, 0.0)
    d.feed(61, False, 0.1)
    d.feed(14, True, 0.2)
    assert ev == ["start", "cancel"]
    d.tick(1.0)
    assert ev == ["start", "cancel"]


def test_other_key_while_locked_does_not_cancel():
    d, ev = mk(tap_ms=250, double_tap_ms=350)
    d.feed(61, True, 0.0); d.feed(61, False, 0.1); d.feed(61, True, 0.25); d.feed(61, False, 0.35)
    assert d.locked
    d.feed(14, True, 2.0)
    assert ev == ["start"] and d.locked


def test_hold_detector_double_tap_lock():
    d, ev = mk(tap_ms=250, double_tap_ms=350)
    d.feed(61, True, 0.0)
    d.feed(61, False, 0.1)
    d.feed(61, True, 0.25)
    d.feed(61, False, 0.35)
    d.tick(5.0)
    assert ev == ["start"] and d.locked
    d.feed(61, True, 6.0)
    d.feed(61, False, 6.1)
    assert ev == ["start", "stop"] and not d.locked


def test_hold_detector_escape_cancels():
    d, ev = mk()
    d.feed(61, True, 0.0)
    d.feed(ESC_KEYCODE, True, 0.5)
    d.feed(61, False, 1.0)
    assert ev == ["start", "cancel"]


def test_escape_when_idle_is_ignored():
    d, ev = mk()
    d.feed(ESC_KEYCODE, True, 0.0)
    assert ev == []


def test_other_keys_are_ignored():
    d, ev = mk()
    d.feed(54, True, 0.0)
    d.feed(54, False, 0.2)
    assert ev == []


# ---- the event tap and the app's own synthetic keys -------------------------------------------

def _key_event(keycode, down, flags=None, type_=None, tag=None):
    import Quartz
    ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    if type_ is not None:
        Quartz.CGEventSetType(ev, type_)
    if flags is not None:
        Quartz.CGEventSetFlags(ev, flags)
    if tag is not None:
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGEventSourceUserData, tag)
    return ev


def test_listener_feeds_modifier_changes_from_real_events():
    import Quartz
    from voz.hotkey import Listener
    d, ev = mk(tap_ms=0)
    lst = Listener(d)
    down = _key_event(61, True, Quartz.kCGEventFlagMaskAlternate, Quartz.kCGEventFlagsChanged)
    up = _key_event(61, False, 0, Quartz.kCGEventFlagsChanged)
    lst._callback(None, Quartz.kCGEventFlagsChanged, down, None)
    lst._callback(None, Quartz.kCGEventFlagsChanged, up, None)
    assert ev == ["start", "stop"]


def test_listener_ignores_the_apps_own_synthetic_keys():
    """MyFlow pastes with a synthetic Cmd+V. The tap used to read that V as a chord and cancel the hold that
    had already started for the next dictation, which then vanished without a trace (2026-10-25)."""
    import Quartz
    from voz.hotkey import OWN_EVENT_TAG, Listener
    d, ev = mk()
    lst = Listener(d)
    d.feed(61, True, 0.0)
    own_v = _key_event(9, True, Quartz.kCGEventFlagMaskCommand, tag=OWN_EVENT_TAG)
    lst._callback(None, Quartz.kCGEventKeyDown, own_v, None)
    assert ev == ["start"]
    someone_elses_v = _key_event(9, True, Quartz.kCGEventFlagMaskCommand)
    lst._callback(None, Quartz.kCGEventKeyDown, someone_elses_v, None)
    assert ev == ["start", "cancel"]
