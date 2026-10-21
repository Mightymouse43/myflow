"""`voz doctor`: a plain-English health report."""

from __future__ import annotations

from pathlib import Path

from . import config

HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"


def _model_cached(model_id: str) -> bool:
    """True only when the weights themselves are present (not just config files or a partial download)."""
    d = HF_HUB / ("models--" + model_id.replace("/", "--")) / "snapshots"
    if not d.exists():
        return False
    for snap in d.iterdir():
        for w in list(snap.glob("*.safetensors")) + list(snap.glob("*.npz")):
            try:
                if w.resolve().exists() and w.resolve().stat().st_size > 1_000_000:
                    return True
            except OSError:
                continue
    return False


def report() -> str:
    from . import history, launchagent
    from .paste import is_trusted

    from . import status

    config.ensure_dirs()
    cfg = config.load()
    lines = ["MyFlow doctor", "============="]
    fix = "NOT granted -> System Settings > Privacy & Security > Accessibility > add MyFlow"
    live = status.read()
    if live:
        lines.append(f"MyFlow app: running (pid {live['pid']}), status: {live.get('text', '')}")
        lines.append(f"Accessibility (as MyFlow sees it): {'granted' if live.get('trusted') else fix}")
    else:
        lines.append("MyFlow app: not running")
        lines.append(f"Accessibility (from this terminal; the menu bar status is authoritative): {'granted' if is_trusted() else fix}")
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        lines.append(f"Microphone input: {dev['name']} ({int(dev['default_samplerate'])} Hz)")
    except Exception as e:  # pragma: no cover
        lines.append(f"Microphone input: not found ({e})")
    lines.append(f"Engine: {cfg.engine}  hotkey: {cfg.hotkey}  language: {cfg.language}  polish: {'on' if cfg.polish else 'off'}")
    for label, mid in (("Whisper", cfg.whisper_model), ("Parakeet", cfg.parakeet_model), ("Polish LLM", cfg.polish_model)):
        lines.append(f"Model {label}: {mid} -> {'cached' if _model_cached(mid) else 'not downloaded yet'}")
    app = Path.home() / "Applications" / "MyFlow.app"
    lines.append(f"MyFlow.app: {'installed at ' + str(app) if app.exists() else 'not built (run scripts/install.sh)'}")
    lines.append(f"Launch at login: {'on' if launchagent.is_enabled() else 'off'}")
    lines.append(f"Config: {config.CONFIG_PATH}  dictionary: {config.DICTIONARY_PATH}")
    n_words = len([l for l in config.DICTIONARY_PATH.read_text().splitlines() if l.strip() and not l.startswith('#')]) if config.DICTIONARY_PATH.exists() else 0
    lines.append(f"Dictionary entries: {n_words}  learned rules: {len(__import__('json').loads(config.LEARNED_PATH.read_text())) if config.LEARNED_PATH.exists() else 0}")
    recs = history.recent(3)
    lines.append(f"Dictations logged: {len(history._read_all())}")
    for r in recs:
        lines.append(f"  {r['ts']}  [{r['app']}] {r['final'][:70]}")
    return "\n".join(lines)
