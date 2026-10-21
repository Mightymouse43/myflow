import importlib
import pytest


@pytest.fixture
def tmp_voz(tmp_path, monkeypatch):
    """Point VOZ_HOME at a temp dir and reload voz.config so paths follow it."""
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import voz.config as c
    importlib.reload(c)
    return tmp_path
