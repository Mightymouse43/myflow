"""The HUD's pure parts: level meter, pill size and placement. AppKit drawing is smoke-tested by running the app."""

import math

import pytest

from voz.hud import COMPACT_W, H, MAX_W, MIN_W, Meter, level_to_unit, pick_screen, pill_origin, pill_width, shown_text


def test_level_to_unit_maps_silence_to_zero_and_loud_speech_to_one():
    assert level_to_unit(0.0) == 0.0
    assert level_to_unit(0.003) == 0.0          # below the speech gate stays flat
    assert 0.4 < level_to_unit(0.02) < 0.7      # normal speaking voice sits mid-scale
    assert level_to_unit(0.2) == 1.0            # loud speech pins the bars


def test_meter_silence_gives_resting_bars():
    m = Meter()
    assert m.update(0.0) == [m.min_h] * 5


def test_meter_centre_bar_tallest_when_loud():
    m = Meter()
    for _ in range(20):
        h = m.update(0.3)
    assert h[2] > h[1] > h[0] and h[1] == h[3] and h[0] == h[4]
    assert h[2] == pytest.approx(m.max_h, abs=0.05)


def test_meter_decays_after_speech_stops():
    m = Meter()
    for _ in range(20):
        m.update(0.3)
    prev = m.update(0.0)
    for _ in range(10):
        cur = m.update(0.0)
        assert all(c <= p for c, p in zip(cur, prev))
        prev = cur
    assert prev[2] < m.max_h * 0.3


def test_meter_idle_wave_stays_inside_the_bar_range():
    m = Meter()
    for t in (0.0, 0.3, 1.1, 2.7):
        h = m.idle(t)
        assert len(h) == 5 and all(m.min_h <= x <= m.max_h for x in h)
    assert m.idle(0.0) != m.idle(0.4)           # it moves


def test_pill_is_half_the_old_height():
    assert H <= 28 and COMPACT_W <= 100


def test_pill_stays_compact_for_listening_thinking_and_done():
    # done is a green flash of the same little pill: Carlos does not want the text repeated
    for state in ("listening", "thinking", "done"):
        assert pill_width(state, text_px=400) == COMPACT_W
    assert shown_text("done", "So the plan is good.") == ""


def test_pill_fits_short_messages_for_errors_and_blocked_pastes():
    assert pill_width("error", text_px=5000) == MAX_W
    assert pill_width("error", text_px=1) == MIN_W
    assert MIN_W < pill_width("error", text_px=100) < MAX_W
    assert shown_text("error", "Didn't catch that") == "Didn't catch that"
    assert shown_text("copied", "the whole dictation") == "Copied, paste blocked"


def test_pill_sits_centred_just_above_the_bottom_of_the_visible_screen():
    visible = ((0.0, 0.0), (1440.0, 900.0))
    assert pill_origin(visible, width=80) == (680.0, 24.0)
    docked = ((0.0, 70.0), (1440.0, 830.0))       # Dock takes the bottom 70 px
    assert pill_origin(docked, width=80) == (680.0, 94.0)
    second = ((1440.0, 0.0), (1920.0, 1080.0))     # a second monitor to the right
    assert pill_origin(second, width=100) == (2350.0, 24.0)


def test_pick_screen_follows_the_mouse_and_falls_back_to_the_first():
    frames = [((0.0, 0.0), (1440.0, 900.0)), ((1440.0, 0.0), (1920.0, 1080.0))]
    assert pick_screen((100.0, 100.0), frames) == 0
    assert pick_screen((1500.0, 100.0), frames) == 1
    assert pick_screen((-50.0, -50.0), frames) == 0


def test_anchor_is_the_front_windows_centre_in_appkit_coordinates():
    """Window bounds come from CoreGraphics (origin top-left of the main screen, y down); AppKit's y goes up."""
    from voz.hud import anchor_point
    # a window on the external screen to the left: CG bounds x=-1900, y=100, 800x600; main screen is 982 tall
    assert anchor_point((-1900.0, 100.0, 800.0, 600.0), primary_height=982.0, mouse=(10.0, 10.0)) == (-1500.0, 582.0)
    assert anchor_point(None, primary_height=982.0, mouse=(10.0, 10.0)) == (10.0, 10.0)


def test_pill_follows_the_window_you_dictate_into_not_the_mouse():
    from voz.hud import anchor_point
    frames = [((0.0, 0.0), (1512.0, 982.0)), ((-1920.0, 0.0), (1920.0, 1080.0))]   # Carlos's desk today
    mouse_on_laptop = (300.0, 400.0)
    claude_on_sceptre = (-1800.0, 50.0, 1500.0, 900.0)
    assert pick_screen(anchor_point(claude_on_sceptre, 982.0, mouse_on_laptop), frames) == 1
    assert pick_screen(anchor_point(None, 982.0, mouse_on_laptop), frames) == 0
    assert pick_screen((100.0, 970.0), frames) == 0     # the menu bar strip still counts as the laptop screen


def test_front_window_skips_invisible_strips_and_overlays():
    """The real Claude window sat behind an alpha-0 1920x32 strip parked above the Sceptre (2026-10-19)."""
    from voz.hud import front_window_bounds_from
    strip = {"kCGWindowOwnerPID": 18179, "kCGWindowLayer": 0, "kCGWindowAlpha": 0.0,
             "kCGWindowBounds": {"X": -1920.0, "Y": -130.0, "Width": 1920.0, "Height": 32.0}}
    real = {"kCGWindowOwnerPID": 18179, "kCGWindowLayer": 0, "kCGWindowAlpha": 1.0,
            "kCGWindowBounds": {"X": -1920.0, "Y": -98.0, "Width": 1920.0, "Height": 1080.0}}
    other = {"kCGWindowOwnerPID": 1, "kCGWindowLayer": 0, "kCGWindowAlpha": 1.0,
             "kCGWindowBounds": {"X": 0.0, "Y": 0.0, "Width": 800.0, "Height": 600.0}}
    overlay = {"kCGWindowOwnerPID": 18179, "kCGWindowLayer": 25, "kCGWindowAlpha": 1.0,
               "kCGWindowBounds": {"X": 0.0, "Y": 0.0, "Width": 800.0, "Height": 600.0}}
    tiny = {"kCGWindowOwnerPID": 18179, "kCGWindowLayer": 0, "kCGWindowAlpha": 1.0,
            "kCGWindowBounds": {"X": 10.0, "Y": 10.0, "Width": 1.0, "Height": 1.0}}
    assert front_window_bounds_from([other, overlay, strip, tiny, real], pid=18179) == (-1920.0, -98.0, 1920.0, 1080.0)
    assert front_window_bounds_from([other, strip], pid=18179) is None


def test_pick_screen_uses_the_nearest_screen_when_the_point_is_off_every_screen():
    frames = [((0.0, 0.0), (1512.0, 982.0)), ((-1920.0, 0.0), (1920.0, 1080.0))]
    assert pick_screen((-960.0, 1096.0), frames) == 1      # just above the Sceptre's top edge
    assert pick_screen((2000.0, 500.0), frames) == 0       # off to the right of the laptop
