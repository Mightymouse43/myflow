from pathlib import Path

import numpy as np
import pytest

from voz.bench import wer
from voz.config import Config

FIX = Path(__file__).parent / "fixtures"


def test_wer():
    assert wer("a b c d", "a b x d") == 0.25


def test_wer_ignores_case_and_punctuation():
    assert wer("Hello, there. How are you?", "hello there how are you") == 0.0


@pytest.mark.slow
@pytest.mark.parametrize("name", ["parakeet", "whisper"])
def test_engine_on_the_sample_clip(name):
    from voz.audio import read_wav
    from voz.engines import load_engine

    eng = load_engine(Config(engine=name))
    eng.load()
    audio, sr = read_wav(FIX / "sample-20s.wav")
    hyp = eng.transcribe(audio, sr)
    assert wer((FIX / "sample-20s.ref.txt").read_text(), hyp) < 0.15


@pytest.mark.slow
def test_whisper_silence_returns_empty():
    from voz.engines import load_engine

    eng = load_engine(Config(engine="whisper"))
    eng.load()
    assert eng.transcribe(np.zeros(16000, dtype=np.float32), 16000).strip() == ""


@pytest.mark.slow
def test_parakeet_silence_returns_empty():
    from voz.engines import load_engine

    eng = load_engine(Config(engine="parakeet"))
    eng.load()
    assert eng.transcribe(np.zeros(16000, dtype=np.float32), 16000).strip() == ""


@pytest.mark.slow
def test_parakeet_transcribes_on_a_different_thread_than_it_loaded_on():
    """The app loads engines on a menu/boot thread while the worker thread (which transcribes) is alive.
    MLX binds unevaluated arrays to the thread that made them, so lazy weights must be materialised at
    load. Both threads stay alive together here; a dead loader thread can lend its id to the worker."""
    import threading

    from voz.audio import read_wav
    from voz.engines import load_engine

    eng = load_engine(Config(engine="parakeet"))
    audio, sr = read_wav(FIX / "sample-20s.wav")
    loaded, done, out = threading.Event(), threading.Event(), {}

    def work():  # the long-lived worker, started first like the app's
        loaded.wait(120)
        try:
            out["text"] = eng.transcribe(audio[: sr * 5], sr)
        except Exception as e:  # pragma: no cover - the failure we are guarding against
            out["error"] = e
        done.set()

    def load():
        eng.load()
        loaded.set()
        done.wait(120)  # stay alive while the worker runs, like a menu thread would

    worker, loader = threading.Thread(target=work), threading.Thread(target=load)
    worker.start(); loader.start()
    worker.join(150); loader.join(5)
    assert "error" not in out, out.get("error")
    assert len(out["text"].split()) >= 5
