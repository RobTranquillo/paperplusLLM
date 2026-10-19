#!/bin/zsh
# Richtet den regelmäßigen Lauf von paperplus.py über launchd ein (alle 6 Stunden, ADR 0004).
#   ./install-launchd.sh               # installieren bzw. aktualisieren und laden
#   ./install-launchd.sh --uninstall   # entfernen
# Log: ~/Library/Logs/paperplusLLM.log
set -e

LABEL="local.paperplusllm"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/paperplusLLM.log"
INTERVAL=21600   # 6 Stunden

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ "$1" == "--uninstall" ]]; then
  rm -f "$PLIST"
  echo "✓ Zeitplan entfernt ($LABEL)"
  exit 0
fi

PYTHON_DIR="$(dirname "$(command -v python3)")"

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$PROJECT_DIR/run.sh</string>
    <string>--auto</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PYTHON_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartInterval</key>
  <integer>$INTERVAL</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✓ Zeitplan eingerichtet: alle $((INTERVAL / 3600)) h, erster Lauf jetzt"
echo "  Python:  $PYTHON_DIR/python3"
echo "  Log:     $LOG"
