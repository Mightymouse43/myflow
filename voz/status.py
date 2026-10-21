"""~/.voz/status.json: what the running app sees (trust, engine, status line), for `voz doctor`."""

from __future__ import annotations

import json
import os
import time

from . import config


def _path():
    return config.VOZ_DIR / "status.json"


def write(**fields) -> None:
    pid = fields.pop("pid", os.getpid())
    data = {"pid": pid, "ts": time.time(), **fields}
    config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, _path())


def read() -> dict | None:
    """The status of a live MyFlow process, or None when there is none."""
    try:
        data = json.loads(_path().read_text())
        pid = int(data["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    return data
