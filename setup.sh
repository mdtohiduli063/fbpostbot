#!/usr/bin/env bash
# =============================================================================
# AI News Bot — One-shot setup + launcher (Ubuntu / Debian / Fedora VPS)
#
#     bash setup.sh                 # install everything AND start the bot
#     bash setup.sh --install-only  # install only, do not launch
#     bash setup.sh --no-sudo       # skip system-package step (CI / no-sudo)
#
# Reads every credential from ``config.json`` — there is no .env file.
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

INSTALL_ONLY=0
USE_SUDO=1
for arg in "$@"; do
    case "$arg" in
        --install-only) INSTALL_ONLY=1 ;;
        --no-sudo)      USE_SUDO=0 ;;
        -h|--help)
            sed -n '2,11p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

SUDO=""
if [ "$USE_SUDO" -eq 1 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

echo "════════════════════════════════════════════════════════════"
echo "  📰  AI News Bot — One-shot Installer"
echo "  Project: $PROJECT_DIR"
echo "════════════════════════════════════════════════════════════"

# ── 1. System packages ──────────────────────────────────────────────────────
echo ""
echo "→ [1/6] Installing system packages..."
if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev python3-pip \
        build-essential pkg-config \
        libjpeg-dev zlib1g-dev libfreetype6-dev \
        libharfbuzz-dev libfribidi-dev \
        libxml2-dev libxslt1-dev \
        fonts-noto fonts-noto-cjk fonts-noto-color-emoji \
        ca-certificates curl git ffmpeg
elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y python3 python3-devel gcc gcc-c++ make pkgconf \
        libjpeg-turbo-devel zlib-devel freetype-devel \
        harfbuzz-devel fribidi-devel libxml2-devel libxslt-devel \
        google-noto-sans-fonts curl git ffmpeg
elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm python python-pip base-devel \
        libjpeg-turbo zlib freetype2 harfbuzz fribidi \
        libxml2 libxslt noto-fonts noto-fonts-emoji ffmpeg curl git
else
    echo "  ⚠️  No supported package manager found — install Python 3.11+, build tools, ffmpeg manually."
fi

# ── 2. Bangla font ──────────────────────────────────────────────────────────
echo ""
echo "→ [2/6] Bangla font..."
mkdir -p assets/fonts
if [ ! -f assets/fonts/NotoSansBengali-Bold.ttf ]; then
    echo "   downloading Noto Sans Bengali..."
    curl -fsSL -o assets/fonts/NotoSansBengali-Bold.ttf \
        "https://github.com/google/fonts/raw/main/ofl/notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf" \
        || echo "   ⚠️  font download failed — will fall back to system fonts."
else
    echo "   already present."
fi

# ── 3. Python virtualenv ────────────────────────────────────────────────────
echo ""
echo "→ [3/6] Python virtualenv (.venv)..."
PY_BIN="$(command -v python3.11 || command -v python3 || command -v python)"
if [ -z "$PY_BIN" ]; then
    echo "   ❌ No python3 interpreter available." >&2
    exit 1
fi
echo "   interpreter: $PY_BIN"
[ -d ".venv" ] || "$PY_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools >/dev/null

# ── 4. Python dependencies ──────────────────────────────────────────────────
echo ""
echo "→ [4/6] Installing Python dependencies (this may take a few minutes)..."
pip install --no-cache-dir -r requirements.txt

# ── 5. Runtime dirs ─────────────────────────────────────────────────────────
echo ""
echo "→ [5/6] Creating runtime directories..."
mkdir -p data/images data/videos logs audio
[ -f audio/.gitkeep ] || touch audio/.gitkeep

# ── 6. Sanity check on config.json ──────────────────────────────────────────
echo ""
echo "→ [6/6] Verifying config.json..."
if [ ! -f config.json ]; then
    echo "   ❌ config.json missing — cannot continue." >&2
    exit 1
fi
python - <<'PY'
import json, sys
with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)
creds = cfg.get("credentials", {}) or {}
need = {
    "facebook_page_id":           "Facebook Page ID",
    "facebook_page_access_token": "Facebook Page Access Token",
    "gemini_api_key":             "Gemini API key",
}
missing = [label for k, label in need.items() if not str(creds.get(k, "")).strip()]
if missing:
    print("   ⚠️  Missing in config.json → credentials: " + ", ".join(missing))
    print("       Bot will still start, but those features will be disabled.")
else:
    print("   ✅ All required credentials present in config.json")
PY

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ✅ Setup complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Start the bot anytime:"
echo "      bash run.sh"
echo "      # or:  source .venv/bin/activate && python main.py"
echo ""
echo "  Drop background-music files into  ./audio/  (NEWSAUDIO1.mp3, …)"
echo ""

# ── Optional: launch the bot immediately ────────────────────────────────────
if [ "$INSTALL_ONLY" -eq 1 ]; then
    echo "  --install-only flag set → not launching the bot."
    exit 0
fi

echo "════════════════════════════════════════════════════════════"
echo "  🚀  Starting the bot now (Ctrl+C to stop)..."
echo "════════════════════════════════════════════════════════════"
exec python main.py
