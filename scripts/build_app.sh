#!/bin/bash
# Build dist/MyFlow.app (Swift launcher + Info.plist) and install it to ~/Applications/MyFlow.app.
# Rebuilding the launcher changes its ad-hoc signature, which makes macOS forget the Accessibility
# grant. So the installed copy is only replaced when the launcher, plist, python path or icon changed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/MyFlow.app"
DEST="$HOME/Applications/MyFlow.app"
PY="$ROOT/.venv/bin/python"

[ -x "$PY" ] || { echo "no venv at $PY; run scripts/install.sh first" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -o "$APP/Contents/MacOS/MyFlow" "$ROOT/launcher/MyFlow.swift"
echo "$PY" > "$APP/Contents/Resources/python_path"
if [ -f "$ROOT/launcher/AppIcon.icns" ]; then cp "$ROOT/launcher/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"; fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>MyFlow</string>
  <key>CFBundleIdentifier</key><string>com.carlosramirez.myflow</string>
  <key>CFBundleName</key><string>MyFlow</string>
  <key>CFBundleDisplayName</key><string>MyFlow</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>MyFlow listens only while you hold the dictation key.</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - --identifier com.carlosramirez.myflow "$APP" 2>/dev/null

mkdir -p "$HOME/Applications"
if [ -d "$DEST" ] && cmp -s "$APP/Contents/MacOS/MyFlow" "$DEST/Contents/MacOS/MyFlow" \
   && cmp -s "$APP/Contents/Info.plist" "$DEST/Contents/Info.plist" \
   && cmp -s "$APP/Contents/Resources/python_path" "$DEST/Contents/Resources/python_path" \
   && cmp -s "$APP/Contents/Resources/AppIcon.icns" "$DEST/Contents/Resources/AppIcon.icns"; then
  echo "MyFlow.app unchanged at $DEST (keeping its permissions)"
else
  rm -rf "$DEST"
  cp -R "$APP" "$DEST"
  echo "installed $DEST"
fi
