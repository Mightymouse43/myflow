"""Command line entry: python -m voz <run|transcribe|doctor|bench|launchagent>."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config


def _setup_logging(to_file: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if to_file:
        config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.LOG_PATH))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=handlers)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voz", description="MyFlow: local hold-to-talk dictation.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="start the menu bar app")
    t = sub.add_parser("transcribe", help="run the full pipeline on a WAV file and print the text")
    t.add_argument("wav")
    t.add_argument("--engine", choices=["parakeet", "whisper"])
    t.add_argument("--raw", action="store_true", help="print the engine output before cleanup too")
    sub.add_parser("doctor", help="check permissions, models, and audio devices")
    b = sub.add_parser("bench", help="benchmark both engines on the sample clip")
    b.add_argument("--wav")
    b.add_argument("--ref")
    la = sub.add_parser("launchagent", help="enable or disable launch at login")
    la.add_argument("state", choices=["enable", "disable", "status"])
    args = p.parse_args(argv)

    if args.cmd == "run":
        _setup_logging(to_file=True)
        from .app import run
        run()
        return 0

    _setup_logging(to_file=False)
    if args.cmd == "transcribe":
        from . import textproc
        from .audio import read_wav
        from .engines import load_engine
        from .vocab import Vocab

        cfg = config.load()
        if args.engine:
            cfg.engine = args.engine
        config.ensure_dirs()
        vocab = Vocab.load()
        eng = load_engine(cfg)
        eng.load()
        audio, sr = read_wav(Path(args.wav))
        raw = eng.transcribe(audio, sr, prompt_words=vocab.words())
        if args.raw:
            print("raw:  ", raw)
        print(vocab.apply(textproc.clean(raw, cfg)))
        return 0
    if args.cmd == "bench":
        from . import bench

        results = bench.run(Path(args.wav) if args.wav else None, Path(args.ref) if args.ref else None)
        print(bench.format_table(results))
        for r in results:
            print(f"\n[{r['name']}] {r['text']}")
        return 0
    if args.cmd == "doctor":
        from .doctor import report

        print(report())
        return 0
    if args.cmd == "launchagent":
        from . import launchagent

        if args.state == "status":
            print("enabled" if launchagent.is_enabled() else "disabled")
        else:
            launchagent.set_enabled(args.state == "enable")
            print("launch at login:", args.state + "d")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
