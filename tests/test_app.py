import time
from pathlib import Path

import numpy as np

from voz import history
from voz.app import Session
from voz.audio import read_wav
from voz.config import Config
from voz.vocab import Vocab

FIX = Path(__file__).parent / "fixtures"
SPEECH, SR = read_wav(FIX / "sample-20s.wav")
SPEECH = SPEECH[: SR * 3]


class FakeEngine:
    name = "fake"

    def __init__(self, texts, delay=0.0):
        self.texts = list(texts)
        self.delay = delay
        self.prompts = []

    def load(self):
        pass

    def transcribe(self, audio, sr, prompt_words=None):
        self.prompts.append(prompt_words)
        time.sleep(self.delay)
        return self.texts.pop(0)


class FakeRecorder:
    def __init__(self, clips):
        self.clips = list(clips)
        self.recording = False
        self.seconds = 0.0
        self.level = 0.0
        self.sr = 16000

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        audio = self.clips.pop(0) if self.clips else np.zeros(0, dtype=np.float32)
        self.seconds = len(audio) / self.sr
        return audio


class FakeHud:
    def __init__(self):
        self.calls = []

    def show(self, state, text=""):
        self.calls.append((state, text))

    def hide(self):
        self.calls.append(("hide", ""))


def make(texts, clips, delay=0.0, cfg=None, vocab=None, frontmost_app=None, caret_fn=None, paste_status="pasted"):
    pasted = []
    hud = FakeHud()
    eng = FakeEngine(texts, delay)
    s = Session(engine=eng, recorder=FakeRecorder(clips), vocab=vocab or Vocab.from_text(""),
                cfg=cfg or Config(save_clips=True), paste_fn=lambda t, d: pasted.append(t) or paste_status,
                hud=hud, frontmost_app=frontmost_app or (lambda: "TestApp"), caret_fn=caret_fn)
    return s, pasted, hud, eng


def test_session_pastes_cleaned_text(tmp_voz):
    s, pasted, hud, eng = make(["um so the the plan is good"], [SPEECH])
    s.on_start()
    s.on_stop()
    assert s.wait_idle(5)
    assert pasted == ["So the plan is good."]
    assert hud.calls[0] == ("listening", "") and hud.calls[-1] == ("done", "So the plan is good.")
    assert eng.prompts == [[]]


def test_session_passes_dictionary_words_to_engine_and_applies_them(tmp_voz):
    v = Vocab.from_text("Higgsfield")
    s, pasted, hud, eng = make(["render it in hicksfield"], [SPEECH], vocab=v)
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    assert eng.prompts == [["Higgsfield"]]
    assert pasted == ["Render it in Higgsfield."]


def test_session_skips_silence(tmp_voz):
    s, pasted, hud, eng = make(["should not be used"], [np.zeros(16000, dtype=np.float32)])
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    assert pasted == []
    assert ("error", "Didn't catch that") in hud.calls
    assert eng.prompts == []


def test_session_ignores_blips_quietly(tmp_voz):
    s, pasted, hud, eng = make(["x"], [np.zeros(3200, dtype=np.float32)])
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    assert pasted == [] and ("error", "Didn't catch that") not in hud.calls
    assert hud.calls[-1] == ("hide", "")


def test_two_quick_dictations_paste_in_order(tmp_voz):
    s, pasted, hud, eng = make(["one", "two"], [SPEECH, SPEECH], delay=0.3,
                               cfg=Config(paste_restore_delay_ms=50))
    s.on_start(); s.on_stop()
    s.on_start(); s.on_stop()
    assert s.wait_idle(5)
    assert pasted == ["One", " Two"]  # same field, no gap before the second


def test_cancel_discards(tmp_voz):
    s, pasted, hud, eng = make(["x"], [SPEECH])
    s.on_start()
    s.on_cancel()
    assert s.wait_idle(5)
    assert pasted == [] and not s.recorder.recording and hud.calls[-1] == ("hide", "")


def test_empty_transcript_shows_error(tmp_voz):
    s, pasted, hud, eng = make([""], [SPEECH])
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    assert pasted == [] and hud.calls[-1] == ("error", "Didn't catch that")


def test_copied_status_shows_copied_hud(tmp_voz):
    hud = FakeHud()
    s = Session(engine=FakeEngine(["hello there friend"]), recorder=FakeRecorder([SPEECH]), vocab=Vocab.from_text(""),
                cfg=Config(), paste_fn=lambda t, d: "copied", hud=hud, frontmost_app=lambda: "X")
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    assert hud.calls[-1] == ("copied", "Hello there friend.")


def test_session_records_history_and_clip(tmp_voz):
    s, pasted, hud, eng = make(["hello there friend"], [SPEECH])
    s.on_start(); s.on_stop(); assert s.wait_idle(5)
    rec = history.last()
    assert rec["final"] == "Hello there friend." and rec["raw"] == "hello there friend" and rec["app"] == "TestApp"
    assert rec["clip"] and Path(rec["clip"]).exists()


def test_fix_last_learns_and_updates_history(tmp_voz):
    v = Vocab.from_text("")
    s, pasted, hud, eng = make([], [], vocab=v)
    history.append("send it to hyper frames", "Send it to hyper frames.", "X", 1.0, None)
    s.fix_last("Send it to HyperFrames.")
    assert history.last()["final"] == "Send it to HyperFrames." and history.last()["corrected"] is True
    assert v.apply("the hyper frames kit") == "the HyperFrames kit"
    assert "HyperFrames" in Vocab.load().words()


def test_choose_engines_never_loads_an_engine_whose_weights_are_missing_when_another_is_cached():
    """Loading an uncached engine means a 2.5 GB download inside the app; use what is on disk instead."""
    from voz.app import choose_engines
    assert choose_engines(Config(engine="parakeet"), cached=lambda m: "whisper" in m) == ["whisper"]
    assert choose_engines(Config(engine="whisper"), cached=lambda m: True) == ["whisper", "parakeet"]
    assert choose_engines(Config(engine="parakeet"), cached=lambda m: True) == ["parakeet", "whisper"]


def test_choose_engines_still_tries_the_configured_engine_on_a_fresh_install():
    from voz.app import choose_engines
    assert choose_engines(Config(engine="whisper"), cached=lambda m: False) == ["whisper"]


# ---- joining one dictation onto the previous one -------------------------------

def _dictate(s, n):
    for _ in range(n):
        s.on_start(); s.on_stop()
    assert s.wait_idle(5)


def test_second_dictation_in_the_same_field_gets_a_space_after_the_period(tmp_voz):
    """Carlos 2026-10-20: 'it doesn't space after the period, it just continues right next to it'."""
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH])
    _dictate(s, 2)
    assert pasted == ["It is good.", " I believe we do."]


def test_caret_reader_wins_when_it_can_see_a_space_before_the_caret(tmp_voz):
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH], caret_fn=lambda: " ")
    _dictate(s, 2)
    assert pasted == ["It is good.", "I believe we do."]


def test_caret_at_the_start_of_a_field_means_no_space(tmp_voz):
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH], caret_fn=lambda: "")
    _dictate(s, 2)
    assert pasted == ["It is good.", "I believe we do."]


def test_caret_reader_sees_a_period_even_when_nothing_was_pasted_before(tmp_voz):
    s, pasted, hud, eng = make(["i believe we do"], [SPEECH], caret_fn=lambda: ".")
    _dictate(s, 1)
    assert pasted == [" I believe we do."]


def test_no_space_when_the_front_app_changed_and_the_caret_is_unreadable(tmp_voz):
    apps = iter(["Notes", "Slack"])
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH], frontmost_app=lambda: next(apps))
    _dictate(s, 2)
    assert pasted == ["It is good.", "I believe we do."]


def test_no_space_when_the_previous_text_only_reached_the_clipboard(tmp_voz):
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH], paste_status="copied")
    _dictate(s, 2)
    assert pasted == ["It is good.", "I believe we do."]


def test_no_space_when_the_previous_dictation_is_old(tmp_voz, monkeypatch):
    import voz.app as app_mod
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH])
    _dictate(s, 1)
    monkeypatch.setattr(app_mod, "JOIN_WINDOW_S", 0.0)
    _dictate(s, 1)
    assert pasted == ["It is good.", "I believe we do."]


def test_hud_and_history_show_the_text_without_the_join_space(tmp_voz):
    s, pasted, hud, eng = make(["it is good", "i believe we do"], [SPEECH, SPEECH])
    _dictate(s, 2)
    assert pasted[1] == " I believe we do."
    assert hud.calls[-1] == ("done", "I believe we do.")
    assert history.last()["final"] == "I believe we do."


# ---- dropped dictations (2026-10-25) ------------------------------------------------------------

def test_paste_waits_until_the_next_hold_is_released(tmp_voz):
    """Take 1 landing while take 2 is already held: its Cmd+V would go out with the hotkey down (Cmd+Option+V)
    and, read back by the tap, cancel take 2. The paste waits for the key to come up instead."""
    s, pasted, hud, eng = make(["one", "two"], [SPEECH, SPEECH], delay=0.2, cfg=Config(paste_restore_delay_ms=50))
    s.on_start(); s.on_stop()          # take 1 queued, transcribing for 0.2 s
    s.on_start()                       # take 2 held before take 1 lands
    time.sleep(0.6)
    assert pasted == []                # nothing pasted while the key is down
    s.on_stop()
    assert s.wait_idle(5)
    assert pasted == ["One", " Two"]


def test_drops_are_logged_with_a_reason(tmp_voz, caplog):
    """Every take that does not reach the engine leaves a line in voz.log; the gate used to drop in silence."""
    caplog.set_level("INFO", logger="voz.app")
    hiss = np.random.default_rng(0).normal(0, 0.006, 32000).astype(np.float32)
    s, pasted, hud, eng = make(["x", "y"], [np.zeros(3200, dtype=np.float32), hiss])
    s.on_start(); s.on_stop(); s.on_start(); s.on_stop(); assert s.wait_idle(5)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("too short" in m for m in msgs), msgs
    assert any("no speech" in m for m in msgs), msgs
    assert pasted == [] and eng.prompts == []


def test_cancel_is_logged(tmp_voz, caplog):
    caplog.set_level("INFO", logger="voz.app")
    s, pasted, hud, eng = make(["x"], [SPEECH])
    s.on_start(); s.on_cancel()
    assert any("cancel" in r.getMessage() for r in caplog.records)


# ---- modal windows need the keyboard (2026-10-26) --------------------------------------------------

class _FakeRunningApp:
    def __init__(self, pid, name="Claude"):
        self.pid, self.name, self.activated = pid, name, 0

    def processIdentifier(self):
        return self.pid

    def activateWithOptions_(self, _opts):
        self.activated += 1


class _FakeApp:
    def __init__(self):
        self.calls = []

    def activateIgnoringOtherApps_(self, flag):
        self.calls.append(("activate", flag))


def test_modal_activates_the_app_before_running_and_hands_focus_back_after():
    """A menu bar app never becomes active by itself, so the Fix window opened with no key window and typing went
    to the front app (Carlos, 2026-10-26)."""
    import os
    from voz.app import with_keyboard
    app, prev = _FakeApp(), _FakeRunningApp(pid=4242)
    order = []
    result = with_keyboard(lambda: order.append("run") or "typed", app=app, frontmost=lambda: prev)
    assert result == "typed"
    assert app.calls == [("activate", True)] and order == ["run"]
    assert prev.activated == 1                      # back to the app the user was dictating into


def test_modal_does_not_reactivate_itself_or_a_missing_front_app():
    import os
    from voz.app import with_keyboard
    app, me = _FakeApp(), _FakeRunningApp(pid=os.getpid())
    assert with_keyboard(lambda: "x", app=app, frontmost=lambda: me) == "x" and me.activated == 0
    assert with_keyboard(lambda: "y", app=app, frontmost=lambda: None) == "y"


def test_modal_hands_focus_back_even_when_the_window_raises():
    from voz.app import with_keyboard
    app, prev = _FakeApp(), _FakeRunningApp(pid=4242)

    def boom():
        raise RuntimeError("alert failed")

    import pytest
    with pytest.raises(RuntimeError):
        with_keyboard(boom, app=app, frontmost=lambda: prev)
    assert prev.activated == 1
