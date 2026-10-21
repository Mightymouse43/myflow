"""User configuration and on-disk layout under ~/.voz (or $VOZ_HOME)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("VOZ_HOME") or (Path.home() / ".voz"))


VOZ_DIR: Path = _home()
CONFIG_PATH: Path = VOZ_DIR / "config.toml"
DICTIONARY_PATH: Path = VOZ_DIR / "dictionary.txt"
LEARNED_PATH: Path = VOZ_DIR / "learned.json"
HISTORY_PATH: Path = VOZ_DIR / "history.jsonl"
CLIPS_DIR: Path = VOZ_DIR / "clips"
LOG_PATH: Path = VOZ_DIR / "voz.log"

DEFAULT_FILLERS = ["um", "uh", "uhm", "erm", "hmm", "mm", "ah", "you know"]

# Words MyFlow should always get right out of the box. Add your own in ~/.voz/dictionary.txt.
SEED_DICTIONARY = [
    "Claude", "Claude Code", "Anthropic", "ChatGPT", "OpenAI", "Whisper", "Parakeet", "MLX",
    "GitHub", "macOS", "iPhone", "iPad", "MacBook", "Wi-Fi", "ffmpeg", "Python", "JavaScript", "TypeScript",
    "Vercel", "Supabase", "Notion", "Figma", "Slack", "Zoom", "Airbnb", "Shopify",
    "TikTok", "Reels", "Shorts", "YouTube", "Instagram", "LinkedIn",
]

DICTIONARY_HEADER = """# MyFlow dictionary. One entry per line.
#   Word                 -> MyFlow will match close-sounding words to this spelling
#   heard form => Word   -> an exact replacement when MyFlow keeps hearing it wrong
# Lines starting with # are ignored.
"""


@dataclass
class Config:
    hotkey: str = "right_option"
    engine: str = "whisper"
    language: str = "en"
    fillers: list[str] = field(default_factory=lambda: list(DEFAULT_FILLERS))
    remove_fillers: bool = True
    spoken_commands: bool = True
    polish: bool = False
    save_clips: bool = True
    clip_retention_mb: int = 2048
    paste_restore_delay_ms: int = 400
    mic_idle_seconds: int = 120   # unused since the AudioQueue recorder (mic closes on key release); kept so old config files still load
    parakeet_model: str = "mlx-community/parakeet-tdt-0.6b-v3"
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    polish_model: str = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"


def ensure_dirs() -> None:
    VOZ_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    if not DICTIONARY_PATH.exists():
        DICTIONARY_PATH.write_text(DICTIONARY_HEADER + "\n".join(SEED_DICTIONARY) + "\n")


def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        data = tomllib.loads(CONFIG_PATH.read_text())
        for f in fields(Config):
            if f.name in data:
                setattr(cfg, f.name, data[f.name])
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"unsupported config value: {v!r}")


def save(cfg: Config) -> None:
    VOZ_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# MyFlow settings. Edit and restart MyFlow, or use the menu bar.", ""]
    for f in fields(Config):
        lines.append(f"{f.name} = {_toml_value(getattr(cfg, f.name))}")
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
