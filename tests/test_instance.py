import os

from voz import instance


def test_second_lock_in_same_home_fails(tmp_voz):
    assert instance.acquire_lock() is True
    assert instance.acquire_lock() is False
    instance.release_lock()
    assert instance.acquire_lock() is True
    instance.release_lock()


def test_parent_alive_without_launcher_env(monkeypatch):
    monkeypatch.delenv("VOZ_LAUNCHER_PID", raising=False)
    assert instance.parent_alive() is True


def test_parent_alive_tracks_launcher_pid(monkeypatch):
    monkeypatch.setenv("VOZ_LAUNCHER_PID", str(os.getppid()))
    assert instance.parent_alive() is True
    monkeypatch.setenv("VOZ_LAUNCHER_PID", "999999999")
    assert instance.parent_alive() is False
