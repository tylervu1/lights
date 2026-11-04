#!/bin/sh
# Installs the lights CLI, the goveed server, and a launchd agent (macOS).
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.tylervu.goveed"

mkdir -p "$HOME/.local/bin" "$HOME/.config/govee" "$HOME/Library/LaunchAgents"

install -m 755 "$BASE/bin/lights" "$HOME/.local/bin/lights"
install -m 644 "$BASE/server/goveed.py" "$BASE/server/webui.html" "$HOME/.config/govee/"

if [ ! -f "$HOME/.config/govee/config.env" ]; then
  install -m 600 "$BASE/config.example.env" "$HOME/.config/govee/config.env"
  echo ">> Add your API key to ~/.config/govee/config.env before starting."
fi
[ -f "$HOME/.config/govee/rooms.json" ] || \
  install -m 644 "$BASE/rooms.example.json" "$HOME/.config/govee/rooms.json"

PY="$(command -v python3)"
cat > "$HOME/Library/LaunchAgents/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$HOME/.config/govee/goveed.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.config/govee/goveed.log</string>
  <key>StandardErrorPath</key><string>$HOME/.config/govee/goveed.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist"

IP="$(ipconfig getifaddr en0 2>/dev/null || echo localhost)"
echo "Installed. CLI: lights | Web UI: http://$IP:8777"
