"""Dictation log (history.jsonl) and the audio clip store used for future fine-tuning."""

from __future__ import annotations

import json
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config


def append(raw: str, final: str, app: str, seconds: float, clip: Path | None) -> dict:
    config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "raw": raw,
        "final": final,
        "app": app,
        "seconds": round(float(seconds), 2),
        "clip": str(clip) if clip else None,
        "corrected": False,
    }
    with config.HISTORY_PATH.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _read_all() -> list[dict]:
    if not config.HISTORY_PATH.exists():
        return []
    out = []
    for line in config.HISTORY_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def recent(n: int) -> list[dict]:
    return list(reversed(_read_all()[-n:])) if n > 0 else []


def last() -> dict | None:
    recs = _read_all()
    return recs[-1] if recs else None


def update_last_final(final: str) -> None:
    recs = _read_all()
    if not recs:
        return
    recs[-1]["final"] = final
    recs[-1]["corrected"] = True
    config.HISTORY_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))


def save_clip(audio: np.ndarray, sr: int) -> Path:
    config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CLIPS_DIR / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".wav")
    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def prune_clips(max_mb: int) -> int:
    if not config.CLIPS_DIR.exists():
        return 0
    files = sorted(config.CLIPS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    budget = max_mb * 1024 * 1024
    removed = 0
    for p in files:
        if total <= budget:
            break
        total -= p.stat().st_size
        p.unlink()
        removed += 1
    return removed
