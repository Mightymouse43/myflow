import json
import wave

import numpy as np

from voz import config, history


def test_append_then_last(tmp_voz):
    history.append(raw="um hello", final="Hello.", app="Notes", seconds=1.2, clip=None)
    rec = history.last()
    assert rec["final"] == "Hello." and rec["raw"] == "um hello" and rec["app"] == "Notes"
    assert "ts" in rec


def test_recent_newest_first(tmp_voz):
    history.append("a", "A.", "X", 1.0, None)
    history.append("b", "B.", "X", 1.0, None)
    history.append("c", "C.", "X", 1.0, None)
    assert [r["final"] for r in history.recent(2)] == ["C.", "B."]


def test_last_is_none_when_empty(tmp_voz):
    assert history.last() is None


def test_save_clip_writes_wav(tmp_voz):
    audio = np.zeros(8000, dtype=np.float32)
    path = history.save_clip(audio, 16000)
    assert path.parent == config.CLIPS_DIR and path.suffix == ".wav"
    with wave.open(str(path)) as w:
        assert w.getnframes() == 8000 and w.getframerate() == 16000 and w.getnchannels() == 1


def test_prune_clips_removes_oldest_first(tmp_voz):
    p1 = history.save_clip(np.zeros(16000, dtype=np.float32), 16000)
    p2 = history.save_clip(np.zeros(16000, dtype=np.float32), 16000)
    assert p1 != p2
    removed = history.prune_clips(max_mb=0)
    assert removed == 2 and not p1.exists() and not p2.exists()


def test_prune_keeps_within_budget(tmp_voz):
    history.save_clip(np.zeros(16000, dtype=np.float32), 16000)  # 32 KB
    assert history.prune_clips(max_mb=1) == 0


def test_update_last_final_rewrites_only_last_line(tmp_voz):
    history.append("a", "A.", "X", 1.0, None)
    history.append("b", "B.", "X", 1.0, None)
    history.update_last_final("B fixed.")
    lines = [json.loads(l) for l in config.HISTORY_PATH.read_text().splitlines()]
    assert [l["final"] for l in lines] == ["A.", "B fixed."]
    assert lines[1]["corrected"] is True
