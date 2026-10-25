"""Keep the speech model's weights in RAM between dictations.

With swap in use, macOS paged Whisper's 1.6 GB of weights out during any pause of a few minutes and the next
take spent 10 to 12 s pulling them back (2026-10-25). MLX can wire its buffers (macOS 15+), which keeps them
resident; the scratch MLX caches during a transcription (about 1 GB) is handed back after every take instead.
"""

from __future__ import annotations

import logging

log = logging.getLogger("voz.residency")

HEADROOM = 1.1  # wire the live weights plus a little, so the first scratch buffers of a take stay resident too


def wired_limit_for(active_bytes: int, max_recommended: int) -> int:
    """Bytes to keep resident: the live weights plus headroom, never above what the system recommends."""
    return min(int(active_bytes * HEADROOM), int(max_recommended))


def pin(mx, enabled: bool = True) -> int:
    """Drop MLX's scratch cache, then wire whatever is still allocated (the model). Returns the bytes wired."""
    try:
        mx.clear_cache()
    except Exception:
        log.debug("clear_cache failed", exc_info=True)
    if not enabled:
        return 0
    try:
        active = int(mx.get_active_memory())
        limit = wired_limit_for(active, mx.device_info().get("max_recommended_working_set_size", 0))
        if limit <= 0:
            return 0
        mx.set_wired_limit(limit)
        log.info("keeping %.0f MB of model weights resident", limit / 1e6)
        return limit
    except Exception:
        log.warning("could not keep the model resident (needs macOS 15+); the first take after a pause may be slow",
                    exc_info=True)
        return 0


def release_scratch(mx) -> None:
    """Give back the activations cached during a transcription; the wired weights stay."""
    try:
        mx.clear_cache()
    except Exception:
        log.debug("clear_cache failed", exc_info=True)
