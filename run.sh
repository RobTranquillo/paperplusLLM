#!/bin/zsh
# Startet paperplus.py aus dem Projektordner; alle Argumente werden durchgereicht.
#   ./paperplus.sh                 # neuestes Dokument
#   ./paperplus.sh --latest 3
#   ./paperplus.sh 1234 1240
set -e

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FEHLER: python3 nicht gefunden (z. B. mit 'xcode-select --install' oder 'brew install python')." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Hinweis: keine .env gefunden – 'cp .env.example .env' und Werte eintragen." >&2
fi

exec python3 -u paperplus.py "$@"
