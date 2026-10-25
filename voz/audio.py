"""Microphone capture (CoreAudio AudioQueue through ctypes), a speech energy gate, and WAV reading.

Why not PortAudio/sounddevice: on macOS 26 Pa_StopStream deadlocks against CoreAudio's IO thread
(AudioOutputUnitStop holds the device mutex while the IsRunning listener on the IO thread waits for
PortAudio's own lock). It froze MyFlow twice in production, once per dictation stop and once at the
idle close two minutes later. AudioQueue is Apple's own recording API and is meant to be started,
stopped and disposed from an app thread.
"""

from __future__ import annotations

import ctypes as C
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("voz.audio")


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


SILENCE_RMS = 0.0005   # loud frames under -66 dBFS: a muted or unplugged microphone
LOUD_RMS = 0.02        # loud frames over -34 dBFS pass on level alone, whatever their dynamics
DYNAMICS = 3.0         # speech's loud frames sit well above its quiet ones (real clips: 5x and up); a fan's do not


def speech_stats(audio: np.ndarray, sr: int = 16000, frame_s: float = 0.02) -> tuple[float, float]:
    """RMS of the quiet (10th percentile) and loud (95th percentile) 20 ms frames of a clip."""
    n = max(1, int(sr * frame_s))
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    if len(frames) == 0:
        return 0.0, 0.0
    levels = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    return float(np.percentile(levels, 10)), float(np.percentile(levels, 95))


def is_speech(audio: np.ndarray, sr: int = 16000) -> bool:
    """True when the clip has the dynamics of speech: its loud frames stand well above its quiet ones.

    Judged against the clip itself, not an absolute level, so a quiet microphone (a MacBook mic at a low input
    volume peaks near 0.008 RMS) still passes while steady room noise, mains hum and a muted mic do not.
    An absolute floor of 0.004 RMS silently dropped the quieter takes of exactly such a mic (2026-10-25)."""
    if audio.size < 1600:  # under 0.1 s at 16 kHz
        return False
    floor, peak = speech_stats(audio, sr)
    return peak > LOUD_RMS or (peak > SILENCE_RMS and peak > floor * DYNAMICS)


def read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32), sr


# ---- CoreAudio AudioQueue input --------------------------------------------------------------

class _ASBD(C.Structure):
    _fields_ = [("mSampleRate", C.c_double), ("mFormatID", C.c_uint32), ("mFormatFlags", C.c_uint32),
                ("mBytesPerPacket", C.c_uint32), ("mFramesPerPacket", C.c_uint32), ("mBytesPerFrame", C.c_uint32),
                ("mChannelsPerFrame", C.c_uint32), ("mBitsPerChannel", C.c_uint32), ("mReserved", C.c_uint32)]


class _AQBuffer(C.Structure):
    _fields_ = [("mAudioDataBytesCapacity", C.c_uint32), ("mAudioData", C.c_void_p), ("mAudioDataByteSize", C.c_uint32),
                ("mUserData", C.c_void_p), ("mPacketDescriptionCapacity", C.c_uint32),
                ("mPacketDescriptions", C.c_void_p), ("mPacketDescriptionCount", C.c_uint32)]


_AQBufferRef = C.POINTER(_AQBuffer)
_InputCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, _AQBufferRef, C.c_void_p, C.c_uint32, C.c_void_p)
_LPCM = 0x6C70636D                      # 'lpcm'
_FLOAT_PACKED = 0x1 | 0x8               # kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked
_at = None


def _audiotoolbox():
    global _at
    if _at is None:
        lib = C.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
        lib.AudioQueueNewInput.argtypes = [C.POINTER(_ASBD), _InputCallback, C.c_void_p, C.c_void_p, C.c_void_p,
                                           C.c_uint32, C.POINTER(C.c_void_p)]
        lib.AudioQueueAllocateBuffer.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(_AQBufferRef)]
        lib.AudioQueueEnqueueBuffer.argtypes = [C.c_void_p, _AQBufferRef, C.c_uint32, C.c_void_p]
        lib.AudioQueueStart.argtypes = [C.c_void_p, C.c_void_p]
        lib.AudioQueueStop.argtypes = [C.c_void_p, C.c_ubyte]
        lib.AudioQueueDispose.argtypes = [C.c_void_p, C.c_ubyte]
        for name in ("AudioQueueNewInput", "AudioQueueAllocateBuffer", "AudioQueueEnqueueBuffer",
                     "AudioQueueStart", "AudioQueueStop", "AudioQueueDispose"):
            getattr(lib, name).restype = C.c_int32
        _at = lib
    return _at


class AudioQueueInput:
    """One recording queue: float32 mono at `sr`, delivered as numpy chunks to `on_chunk` from CoreAudio's thread.

    CoreAudio resamples from the device rate for us. Create, start, stop, close: nothing is kept open.
    """

    def __init__(self, sr: int, on_chunk: Callable[[np.ndarray], None], buffer_s: float = 0.02, n_buffers: int = 8):
        self.sr, self._on_chunk = sr, on_chunk
        self._at = _audiotoolbox()
        self._q = C.c_void_p()
        self._cb = _InputCallback(self._callback)           # keep the trampoline alive for the queue's lifetime
        fmt = _ASBD(float(sr), _LPCM, _FLOAT_PACKED, 4, 1, 4, 1, 32, 0)
        self._check(self._at.AudioQueueNewInput(C.byref(fmt), self._cb, None, None, None, 0, C.byref(self._q)), "AudioQueueNewInput")
        nbytes = max(1, int(sr * buffer_s)) * 4
        for _ in range(n_buffers):
            ref = _AQBufferRef()
            self._check(self._at.AudioQueueAllocateBuffer(self._q, nbytes, C.byref(ref)), "AudioQueueAllocateBuffer")
            self._check(self._at.AudioQueueEnqueueBuffer(self._q, ref, 0, None), "AudioQueueEnqueueBuffer")

    @staticmethod
    def _check(status: int, what: str) -> None:
        if status != 0:
            raise OSError(status, f"{what} failed with OSStatus {status}")

    def _callback(self, _user, aq, buf, _ts, _npackets, _descs) -> None:
        try:
            b = buf.contents
            if b.mAudioDataByteSize:
                self._on_chunk(np.frombuffer(C.string_at(b.mAudioData, b.mAudioDataByteSize), dtype=np.float32).copy())
            if self._q:
                self._at.AudioQueueEnqueueBuffer(aq, buf, 0, None)
        except Exception:
            log.exception("audio buffer callback failed")

    def start(self) -> None:
        self._check(self._at.AudioQueueStart(self._q, None), "AudioQueueStart")

    def stop(self) -> None:
        if self._q:
            self._check(self._at.AudioQueueStop(self._q, 1), "AudioQueueStop")

    def close(self) -> None:
        q, self._q = self._q, C.c_void_p()
        if q:
            self._at.AudioQueueDispose(q, 1)


def _restart_app(reason: str) -> None:
    """Last resort: launchd (KeepAlive on failure) brings MyFlow back in seconds instead of leaving it frozen."""
    log.critical("%s; exiting so launchd restarts MyFlow", reason)
    os._exit(70)


class Recorder:
    """Buffers mono float32 audio from the default input while a dictation is held.

    A fresh AudioQueue per dictation: nothing stays open between holds, so the mic indicator goes
    off as soon as you let go. stop() runs under a watchdog: if CoreAudio ever hangs, on_stuck is
    called (default: exit so launchd restarts the app) rather than freezing the hotkey thread.
    """

    def __init__(self, sr: int = 16000, queue_factory: Callable | None = None,
                 stop_timeout_s: float = 3.0, on_stuck: Callable[[str], None] | None = None):
        self.sr = sr
        self._factory = queue_factory or (lambda sr, on_chunk: AudioQueueInput(sr, on_chunk))
        self._stop_timeout_s = stop_timeout_s
        self._on_stuck = on_stuck or _restart_app
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()      # guards _chunks
        self._slock = threading.Lock()     # serialises start/stop
        self._queue = None
        self._armed = False
        self.level = 0.0
        self.seconds = 0.0

    def _on_chunk(self, chunk: np.ndarray) -> None:
        if not self._armed:
            return
        with self._lock:
            self._chunks.append(chunk)
        self.level = rms(chunk)

    def start(self) -> None:
        with self._slock:
            if self._armed:
                return
            with self._lock:
                self._chunks = []
            self.seconds = 0.0
            queue = self._factory(self.sr, self._on_chunk)
            try:
                queue.start()
            except Exception:
                self._close_quietly(queue)
                raise
            self._queue = queue
            self._armed = True

    def stop(self) -> np.ndarray:
        with self._slock:
            if not self._armed:
                return np.zeros(0, dtype=np.float32)
            self._armed = False
            queue, self._queue = self._queue, None
            self._stop_under_watchdog(queue)
            with self._lock:
                audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
                self._chunks = []
            self.seconds = len(audio) / self.sr
            self.level = 0.0
        return audio

    def _stop_under_watchdog(self, queue) -> None:
        done = threading.Event()

        def _stop():
            try:
                queue.stop()
            except Exception:
                log.exception("stopping the input queue failed")
            finally:
                self._close_quietly(queue)
                done.set()

        threading.Thread(target=_stop, name="voz-audio-stop", daemon=True).start()
        if not done.wait(self._stop_timeout_s):
            self._on_stuck(f"microphone stop did not return within {self._stop_timeout_s:.1f}s")

    @staticmethod
    def _close_quietly(queue) -> None:
        try:
            queue.close()
        except Exception:
            log.exception("closing the input queue failed")

    @property
    def recording(self) -> bool:
        return self._armed
