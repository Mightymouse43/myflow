"""Word error rate and a two-engine benchmark on the sample clip."""

from __future__ import annotations

import re
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _words(s: str) -> list[str]:
    return re.sub(r"[^\w\s']", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    # classic Levenshtein over words
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / len(r)


def run(wav: Path | None = None, ref: Path | None = None, engines: tuple[str, ...] = ("parakeet", "whisper")) -> list[dict]:
    from .audio import read_wav
    from .config import Config
    from .engines import load_engine

    wav = wav or FIXTURES / "sample-20s.wav"
    ref = ref or FIXTURES / "sample-20s.ref.txt"
    audio, sr = read_wav(wav)
    ref_text = ref.read_text()
    results = []
    for name in engines:
        eng = load_engine(Config(engine=name))
        t0 = time.perf_counter()
        eng.load()
        load_s = time.perf_counter() - t0
        eng.transcribe(audio[: sr * 2], sr)  # warm up
        t1 = time.perf_counter()
        hyp = eng.transcribe(audio, sr)
        secs = time.perf_counter() - t1
        results.append({"name": name, "wer": round(wer(ref_text, hyp), 4), "seconds": round(secs, 2),
                        "load_seconds": round(load_s, 1), "text": hyp})
    return results


def format_table(results: list[dict]) -> str:
    lines = [f"{'engine':10} {'WER':>6} {'secs':>6} {'load':>6}"]
    for r in results:
        lines.append(f"{r['name']:10} {r['wer']*100:5.1f}% {r['seconds']:6.2f} {r['load_seconds']:6.1f}")
    return "\n".join(lines)
