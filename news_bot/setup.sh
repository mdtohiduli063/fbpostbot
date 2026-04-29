#!/usr/bin/env bash
# One-shot setup script for Ubuntu 22.04+ VPS deployment.
# Usage:  bash setup.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=== AI News Bot setup ==="
echo "Project directory: $PROJECT_DIR"

# 1. System packages -------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
  echo "→ Installing system packages..."
  sudo apt-get update -y
  sudo apt-get install -y \
      python3.11 python3.11-venv python3-pip \
      fonts-noto fonts-noto-cjk fonts-noto-color-emoji \
      libjpeg-dev zlib1g-dev libfreetype6-dev \
      ca-certificates curl
fi

# 2. Bangla font -----------------------------------------------------------
mkdir -p assets/fonts
if [ ! -f assets/fonts/NotoSansBengali-Bold.ttf ]; then
  echo "→ Downloading Noto Sans Bengali font..."
  curl -fsSL -o assets/fonts/NotoSansBengali-Bold.ttf \
    https://github.com/google/fonts/raw/main/ofl/notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf \
    || echo "  (font download failed — bot will fall back to default font)"
fi

# 3. Python venv & deps ----------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "→ Creating virtualenv..."
  python3.11 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt

# 4. .env template ---------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ Created .env  — fill in your API keys before starting!"
fi

mkdir -p data/images logs

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Test:    .venv/bin/python -m news_bot.main"
echo "  3. Install service:  sudo cp news-bot.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now news-bot"
