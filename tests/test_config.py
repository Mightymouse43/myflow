import importlib


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import voz.config as c
    importlib.reload(c)
    cfg = c.load()
    assert cfg.hotkey == "right_option" and cfg.engine == "whisper"
    assert "um" in cfg.fillers and "like" not in cfg.fillers


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import voz.config as c
    importlib.reload(c)
    cfg = c.load()
    cfg.engine = "whisper"
    c.save(cfg)
    assert c.load().engine == "whisper"
    assert (tmp_path / "config.toml").exists()


def test_ensure_dirs_seeds_dictionary(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZ_HOME", str(tmp_path))
    import voz.config as c
    importlib.reload(c)
    c.ensure_dirs()
    assert (tmp_path / "clips").is_dir()
    seeded = (tmp_path / "dictionary.txt").read_text()
    assert "GitHub" in seeded and "Jimena" not in seeded  # neutral starter list, nobody's names
