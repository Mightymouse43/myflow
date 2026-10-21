#!/bin/bash
# One-shot install: venv, package, models, MyFlow.app, launch at login. Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WITH_PARAKEET=0
for a in "$@"; do [ "$a" = "--with-parakeet" ] && WITH_PARAKEET=1; done

# ---- preflight: this only runs on an Apple Silicon Mac, macOS 14+, with Apple's command line tools ----
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "MyFlow needs a Mac with Apple Silicon (M1 or newer). On another system, see 'Not on a Mac?' in README.md." >&2
  exit 1
fi
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$MACOS_MAJOR" -lt 14 ]; then
  echo "MyFlow needs macOS 14 or newer (this Mac runs $(sw_vers -productVersion))." >&2
  exit 1
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Apple's command line tools are missing. Opening the installer: click Install, wait for it to finish, then run this script again."
  xcode-select --install 2>/dev/null || true
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "installing uv (Python package manager)..."
  if command -v brew >/dev/null 2>&1; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo "uv did not install; see https://docs.astral.sh/uv/" >&2; exit 1; }
fi
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -e ".[dev,polish]" hf_transfer >/dev/null
.venv/bin/python -c "import voz.config as c; c.ensure_dirs()"

echo "Checking the Whisper model (one-time 1.6 GB download if missing)..."
HF_HUB_DISABLE_XET=1 .venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/whisper-large-v3-turbo')" 2>/dev/null
if [ "$WITH_PARAKEET" = "1" ]; then
  echo "Fetching Parakeet v3 (2.5 GB)..."
  HF_HUB_DISABLE_XET=1 .venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/parakeet-tdt-0.6b-v3')"
fi

scripts/build_app.sh
.venv/bin/python -m voz launchagent enable

cat <<MSG

MyFlow is installed and running (look for "MyFlow" in the menu bar).

Two clicks only you can do:
  1. Accessibility: System Settings > Privacy & Security > Accessibility > turn on MyFlow.
     (MyFlow opens that pane on first launch. This is what lets it hear the key and paste.)
  2. Microphone: click Allow the first time you hold the key.

Then hold Right Option, talk, let go. Double-tap it to lock hands-free; Esc cancels.
Check status any time:  .venv/bin/python -m voz doctor
MSG
