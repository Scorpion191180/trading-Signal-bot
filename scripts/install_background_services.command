#!/bin/zsh
set -e

SCRIPT_DIRECTORY="${0:A:h}"
REPOSITORY="${SCRIPT_DIRECTORY:h}"
cd "$REPOSITORY"

./.venv/bin/python scripts/install_background_bot.py

echo ""
echo "Trading-Signal-Dienste wurden installiert."
echo "Web-App: http://localhost:8502/"
