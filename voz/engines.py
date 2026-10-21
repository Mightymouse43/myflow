"""Speech engines: Parakeet (MLX) and Whisper (MLX) behind one small interface."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Protocol

import numpy as np

from .config import Config

log = logging.getLogger("voz.engines")

# Whisper invents these on silence or noise. If that is all it heard, it heard nothing.
_WHISPER_GHOSTS = {
    "thank you", "thanks for watching", "thank you for watching", "subtitles by the amazing.org community",
    "you", "bye", "the end", "so", "oh", "i'm sorry", "thank you very much", "please subscribe",
}


class Engine(Protocol):
    name: str

    def load(self) -> None: ...

    def transcribe(self, audio: np.ndarray, sr: int, prompt_words: list[str] | None = None) -> str: ...


def _as_mono_f32(audio: np.ndarray) -> np.ndarray:
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1)
    return np.ascontiguousarray(a)


def _resample(audio: np.ndarray, sr: int, target: int = 16000) -> np.ndarray:
    if sr == target:
        return audio
    n = int(round(len(audio) * target / sr))
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class ParakeetEngine:
    name = "parakeet"
    LONG_CLIP_SECONDS = 90.0

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._model = None

    def load(self) -> None:
        if self._model is None:
            import mlx.core as mx
            from parakeet_mlx import from_pretrained

            log.info("loading %s", self.model_id)
            model = from_pretrained(self.model_id)
            # from_pretrained leaves the weights lazy (a load + astype graph). MLX binds unevaluated arrays to
            # the thread that created them, so transcribing on the worker thread after loading on a menu or
            # boot thread died with "There is no Stream(cpu, N) in current thread". Materialise them here.
            # mlx_whisper evaluates its weights at load, which is why Whisper never hit this.
            mx.eval(model.parameters())
            self._model = model

    def transcribe(self, audio: np.ndarray, sr: int, prompt_words: list[str] | None = None) -> str:
        self.load()
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        a = _resample(_as_mono_f32(audio), sr)
        cfg = self._model.preprocessor_config
        if len(a) < cfg.hop_length * 4:
            return ""
        if len(a) / cfg.sample_rate > self.LONG_CLIP_SECONDS:
            # Let the library chunk and merge long recordings from a temp file.
            import wave

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                path = Path(tmp.name)
            pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(cfg.sample_rate); w.writeframes(pcm.tobytes())
            try:
                return self._model.transcribe(path, chunk_duration=120.0, overlap_duration=15.0).text.strip()
            finally:
                path.unlink(missing_ok=True)
        # float32, not bfloat16: get_logmel reinterprets the complex spectrum in the input's dtype, so a
        # 2-byte input doubles the bin count and the filterbank matmul fails. The library's own loader is float32.
        mel = get_logmel(mx.array(a).astype(mx.float32), cfg)
        return self._model.generate(mel)[0].text.strip()


class WhisperEngine:
    name = "whisper"

    def __init__(self, model_id: str, language: str = "en"):
        self.model_id = model_id
        self.language = None if language in ("", "auto") else language
        self._loaded = False

    def load(self) -> None:
        if not self._loaded:
            import mlx_whisper

            log.info("loading %s", self.model_id)
            # mlx_whisper caches the model after the first call; a 0.5 s warm-up loads it.
            mlx_whisper.transcribe(np.zeros(8000, dtype=np.float32), path_or_hf_repo=self.model_id,
                                   language=self.language, fp16=True, verbose=None)
            self._loaded = True

    def transcribe(self, audio: np.ndarray, sr: int, prompt_words: list[str] | None = None) -> str:
        import mlx_whisper

        a = _resample(_as_mono_f32(audio), sr)
        if len(a) < 1600:
            return ""
        prompt = ", ".join(prompt_words[:60]) if prompt_words else None
        res = mlx_whisper.transcribe(
            a, path_or_hf_repo=self.model_id, language=self.language, initial_prompt=prompt,
            condition_on_previous_text=False, no_speech_threshold=0.6, fp16=True, verbose=None,
        )
        self._loaded = True
        segs = res.get("segments") or []
        if not segs:
            return ""
        if all(s.get("no_speech_prob", 0.0) > 0.6 for s in segs):
            return ""
        text = " ".join(s["text"].strip() for s in segs if s.get("no_speech_prob", 0.0) <= 0.6).strip()
        if text.lower().strip(" .!?,") in _WHISPER_GHOSTS and len(a) / 16000 < 4.0:
            return ""
        return text


def load_engine(cfg: Config) -> Engine:
    if cfg.engine == "whisper":
        return WhisperEngine(cfg.whisper_model, cfg.language)
    if cfg.engine == "parakeet":
        return ParakeetEngine(cfg.parakeet_model)
    raise ValueError(f"unknown engine {cfg.engine!r} (use parakeet or whisper)")
