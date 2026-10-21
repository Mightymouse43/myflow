"""One MyFlow at a time, and exit when the launcher that spawned us is gone."""

from __future__ import annotations

import fcntl
import os

from . import config

_lock_fd: int | None = None
_INITIAL_PPID = os.getppid()


def acquire_lock() -> bool:
    """Take ~/.voz/voz.lock. False when another MyFlow already holds it."""
    global _lock_fd
    config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(config.VOZ_DIR / "voz.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _lock_fd = fd
    return True


def release_lock() -> None:
    global _lock_fd
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(_lock_fd)
            _lock_fd = None


def parent_alive() -> bool:
    """False once the MyFlow.app launcher that started this process has died (we were reparented)."""
    env = os.environ.get("VOZ_LAUNCHER_PID")
    if env:
        try:
            return os.getppid() == int(env)
        except ValueError:
            return True
    if _INITIAL_PPID <= 1:
        return True  # started by launchd or a shell directly; nothing to track
    return os.getppid() == _INITIAL_PPID
