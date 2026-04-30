#!/usr/bin/env bash
# Quick launcher — activates the venv and runs the bot.
# If the venv is missing, runs setup.sh first.

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "→ .venv not found, running setup.sh first..."
    bash setup.sh --install-only
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec python main.py
