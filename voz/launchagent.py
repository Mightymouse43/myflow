"""Launch at login via a per-user LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.carlosramirez.myflow"
OLD_LABELS = ("com.carlosramirez.voz",)
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
APP_LAUNCHER = Path.home() / "Applications" / "MyFlow.app" / "Contents" / "MacOS" / "MyFlow"


def program_arguments() -> list[str]:
    if APP_LAUNCHER.exists():
        return [str(APP_LAUNCHER)]
    return [sys.executable, "-m", "voz", "run"]


def is_enabled() -> bool:
    return PLIST.exists()


def _retire_old_labels(uid: int) -> None:
    for old in OLD_LABELS:
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{old}"], capture_output=True)
        (PLIST.parent / f"{old}.plist").unlink(missing_ok=True)


def set_enabled(enabled: bool) -> None:
    uid = os.getuid()
    _retire_old_labels(uid)
    if enabled:
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "Label": LABEL,
            "ProgramArguments": program_arguments(),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ProcessType": "Interactive",
            "StandardOutPath": str(Path.home() / ".voz" / "launchd.out.log"),
            "StandardErrorPath": str(Path.home() / ".voz" / "launchd.err.log"),
        }
        PLIST.write_bytes(plistlib.dumps(data))
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], capture_output=True)
    else:
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        PLIST.unlink(missing_ok=True)
