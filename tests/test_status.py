import os

from voz import doctor, status


def test_status_roundtrip(tmp_voz):
    status.write(trusted=True, engine="whisper", text="Ready")
    s = status.read()
    assert s["trusted"] is True and s["engine"] == "whisper" and s["pid"] == os.getpid() and s["text"] == "Ready"


def test_status_read_is_none_when_missing_or_pid_dead(tmp_voz):
    assert status.read() is None
    status.write(trusted=True, engine="whisper", text="Ready", pid=999999999)
    assert status.read() is None


def test_doctor_prefers_the_running_apps_view(tmp_voz):
    status.write(trusted=True, engine="whisper", text="Ready: hold Right Option and talk")
    rep = doctor.report()
    assert "as MyFlow sees it" in rep and "granted" in rep and "Ready: hold Right Option and talk" in rep


def test_doctor_caveats_the_terminal_view_when_app_is_not_running(tmp_voz):
    assert "from this terminal" in doctor.report()
