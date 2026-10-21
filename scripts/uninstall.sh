#!/bin/bash
# Stops MyFlow, removes the login item and the app. Keeps ~/.voz (dictionary, history, clips) unless --purge.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/.venv/bin/python" -m voz launchagent disable 2>/dev/null || true
pkill -f "MyFlow.app/Contents/MacOS/MyFlow" 2>/dev/null || true
pkill -f "\-m voz run" 2>/dev/null || true
rm -rf "$HOME/Applications/MyFlow.app"
if [ "${1:-}" = "--purge" ]; then rm -rf "$HOME/.voz"; echo "removed ~/.voz"; fi
echo "MyFlow removed. Repo and venv left at $ROOT."
