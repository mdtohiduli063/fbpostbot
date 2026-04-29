#!/usr/bin/env bash
# =============================================================================
# AI News Bot — One-shot setup script for Ubuntu / Debian VPS (22.04+, 24.04)
#
# Usage:
#     bash setup.sh
#
# What it does:
#   1. Installs system packages (Python 3.11, build deps, fonts)
#   2. Downloads the Bangla font
#   3. Creates a Python virtualenv (.venv)
#   4. Installs Python dependencies from requirements.txt
#   5. Creates .env from .env.example (if missing)
#   6. Creates data/ + logs/ directories
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "════════════════════════════════════════════════════════════"
echo "  AI News Bot — VPS Setup"
echo "  Project directory: $PROJECT_DIR"
echo "════════════════════════════════════════════════════════════"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
if command -v apt-get >/dev/null 2>&1; then
    echo "→ [1/5] Installing system packages (sudo required)..."
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev python3-pip \
        build-essential pkg-config \
        libjpeg-dev zlib1g-dev libfreetype6-dev \
        libharfbuzz-dev libfribidi-dev \
        libxml2-dev libxslt1-dev \
        fonts-noto fonts-noto-cjk fonts-noto-color-emoji \
        ca-certificates curl git ffmpeg

    # python3.11 may not exist on Debian 12 / Ubuntu 24.04 by default → fallback
    if ! command -v python3.11 >/dev/null 2>&1; then
        echo "  python3.11 not found — installing python3 + venv as fallback"
        sudo apt-get install -y python3 python3-venv python3-dev
    fi
elif command -v dnf >/dev/null 2>&1; then
    echo "→ [1/5] Installing system packages via dnf (RHEL/Fedora)..."
    sudo dnf install -y python3.11 python3.11-devel gcc gcc-c++ make \
        libjpeg-turbo-devel zlib-devel freetype-devel \
        harfbuzz-devel fribidi-devel libxml2-devel libxslt-devel \
        google-noto-sans-fonts curl git ffmpeg
else
    echo "⚠️  No supported package manager (apt-get/dnf) found."
    echo "    Install Python 3.11+, build tools, libjpeg, zlib, freetype, ffmpeg manually."
fi
echo ""

# ── 2. Bangla font ──────────────────────────────────────────────────────────
echo "→ [2/5] Setting up Bangla font..."
mkdir -p assets/fonts
if [ ! -f assets/fonts/NotoSansBengali-Bold.ttf ]; then
    echo "  Downloading Noto Sans Bengali..."
    curl -fsSL -o assets/fonts/NotoSansBengali-Bold.ttf \
        "https://github.com/google/fonts/raw/main/ofl/notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf" \
        || echo "  ⚠️  Font download failed — bot will fall back to system fonts."
else
    echo "  Font already present."
fi
echo ""

# ── 3. Python virtualenv ────────────────────────────────────────────────────
echo "→ [3/5] Creating Python virtualenv (.venv)..."
PY_BIN="$(command -v python3.11 || command -v python3)"
echo "  Using interpreter: $PY_BIN"
if [ ! -d ".venv" ]; then
    "$PY_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
echo ""

# ── 4. Python dependencies ──────────────────────────────────────────────────
echo "→ [4/5] Installing Python dependencies (this may take a few minutes)..."
pip install --no-cache-dir -r requirements.txt
echo ""

# ── 5. .env template + runtime dirs ─────────────────────────────────────────
echo "→ [5/5] Preparing runtime directories + .env..."
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "  Created .env  — fill in your API keys before starting!"
fi
mkdir -p data/images data/videos logs
echo ""

echo "════════════════════════════════════════════════════════════"
echo "  ✅ Setup complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Edit .env and config.json with your API keys / FB credentials"
echo "  2. Quick test:"
echo "         .venv/bin/python main.py"
echo ""
echo "  3. Run as a 24/7 background service (systemd):"
echo "         sudo cp news-bot.service /etc/systemd/system/"
echo "         sudo sed -i \"s|/opt/news_bot|$PROJECT_DIR|g\" /etc/systemd/system/news-bot.service"
echo "         sudo sed -i \"s|User=newsbot|User=$USER|g; s|Group=newsbot|Group=$USER|g\" /etc/systemd/system/news-bot.service"
echo "         sudo systemctl daemon-reload"
echo "         sudo systemctl enable --now news-bot"
echo "         sudo journalctl -u news-bot -f       # live logs"
echo ""
