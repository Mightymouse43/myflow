import sys
import time
from pathlib import Path

import numpy as np
import pytest

from voz.audio import Recorder, is_speech, read_wav

FIX = Path(__file__).parent / "fixtures"


def test_is_speech_false_for_silence():
    assert is_speech(np.zeros(16000, dtype=np.float32)) is False


def test_is_speech_false_for_empty():
    assert is_speech(np.zeros(0, dtype=np.float32)) is False


def test_is_speech_true_for_fixture():
    audio, sr = read_wav(FIX / "sample-20s.wav")
    assert sr == 16000 and audio.dtype == np.float32 and audio.ndim == 1
    assert is_speech(audio) is True


def test_read_wav_scales_to_unit_range():
    audio, _ = read_wav(FIX / "sample-20s.wav")
    assert 0.05 < float(np.abs(audio).max()) <= 1.0


# ---- Recorder on top of a fake AudioQueue ----------------------------------------------------

class FakeQueue:
    def __init__(self, sr, on_chunk, *, fail_start=False, slow_stop=0.0, raise_stop=False):
        self.sr, self.on_chunk = sr, on_chunk
        self.fail_start, self.slow_stop, self.raise_stop = fail_start, slow_stop, raise_stop
        self.started = self.stopped = self.closed = False

    def start(self):
        if self.fail_start:
            raise OSError("no microphone")
        self.started = True

    def stop(self):
        if self.slow_stop:
            time.sleep(self.slow_stop)
        if self.raise_stop:
            raise RuntimeError("device gone")
        self.stopped = True

    def close(self):
        self.closed = True


def _rec(**kw):
    made, stuck = [], []

    def factory(sr, on_chunk):
        q = FakeQueue(sr, on_chunk, **kw)
        made.append(q)
        return q

    return Recorder(sr=16000, queue_factory=factory, stop_timeout_s=0.2, on_stuck=stuck.append), made, stuck


def test_recorder_uses_a_fresh_queue_per_dictation_and_closes_it():
    """A queue lives only while the key is held: no idle stream, nothing to stop later, nothing to deadlock."""
    rec, made, _ = _rec()
    rec.start()
    assert rec.recording is True and len(made) == 1 and made[0].started
    made[0].on_chunk(np.ones(10, dtype=np.float32))
    made[0].on_chunk(np.ones(5, dtype=np.float32))
    audio = rec.stop()
    assert len(audio) == 15 and audio.dtype == np.float32
    assert rec.recording is False and made[0].stopped and made[0].closed
    rec.start()
    assert len(made) == 2 and made[1].started and not made[1].closed
    assert len(rec.stop()) == 0


def test_recorder_ignores_chunks_outside_a_dictation():
    rec, made, _ = _rec()
    rec.start()
    q = made[0]
    rec.stop()
    q.on_chunk(np.ones(10, dtype=np.float32))     # a late buffer after stop
    rec.start()
    assert len(rec.stop()) == 0


def test_recorder_reports_level_and_seconds():
    rec, made, _ = _rec()
    rec.start()
    made[0].on_chunk(np.full(1600, 0.5, dtype=np.float32))
    assert rec.level == pytest.approx(0.5)
    rec.stop()
    assert rec.seconds == pytest.approx(0.1) and rec.level == 0.0


def test_recorder_stop_without_start_is_a_no_op():
    rec, made, _ = _rec()
    assert len(rec.stop()) == 0 and made == [] and rec.recording is False


def test_recorder_start_failure_leaves_it_idle_and_the_next_start_retries():
    made = []
    attempts = {"n": 0}

    def factory(sr, on_chunk):
        attempts["n"] += 1
        q = FakeQueue(sr, on_chunk, fail_start=attempts["n"] == 1)
        made.append(q)
        return q

    rec = Recorder(sr=16000, queue_factory=factory)
    with pytest.raises(OSError):
        rec.start()
    assert rec.recording is False and made[0].closed      # the failed queue is not kept around
    rec.start()
    assert rec.recording is True and len(made) == 2
    rec.stop()


def test_recorder_stop_survives_a_queue_error():
    rec, made, stuck = _rec(raise_stop=True)
    rec.start()
    made[0].on_chunk(np.ones(100, dtype=np.float32))
    audio = rec.stop()
    assert len(audio) == 100 and rec.recording is False and made[0].closed and stuck == []


def test_recorder_watchdog_reports_a_stop_that_hangs():
    """If CoreAudio ever wedges again the app must not freeze with it: the watchdog hands off a restart."""
    rec, made, stuck = _rec(slow_stop=1.0)
    rec.start()
    t0 = time.monotonic()
    audio = rec.stop()
    assert time.monotonic() - t0 < 0.8                     # did not wait for the hung stop
    assert rec.recording is False and len(audio) == 0
    assert len(stuck) == 1 and "stop" in stuck[0].lower()


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio only")
def test_recorder_half_second_on_the_real_microphone():
    rec = Recorder(sr=16000)
    rec.start()
    time.sleep(0.5)
    audio = rec.stop()
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert 0.4 * 16000 <= len(audio) <= 0.8 * 16000
    assert abs(rec.seconds - len(audio) / 16000) < 0.01
    assert rec.recording is False
