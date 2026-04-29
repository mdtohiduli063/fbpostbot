# AI News Bot (Bangla) — Image + Video

Production-grade Python 3.11 bot that:

1. Pulls Bangladeshi news from RSS / HTML sources, summarizes in Bangla
   (Gemini, with safe fallback when quota is hit), generates a modern 1080×1080
   image post, and publishes to Facebook (Telegram / WordPress optional).
2. Discovers **copyright-free news videos** (Wikimedia Commons, Internet
   Archive, optional Pexels / Pixabay / VOA) on Bangladesh / South Asia
   topics, watermarks them with full credit + brand stamp via ffmpeg, and
   publishes to the same Facebook Page with a fully-attributed caption.
3. Auto-cleans its own caches (images, videos, reports, logs, events) on a
   TTL + size-cap basis so the disk never fills up.
4. Runs in **real-time mode** by default: every 2 minutes it polls all
   configured news sources, and every newly published article is summarised,
   rendered, and posted to the Facebook Page immediately (throttled by
   `min_seconds_between_posts`). The local image file is deleted right after
   the FB post succeeds (`delete_image_after_post`).

## Architecture (flat layout — everything at project root)

```
.
├── main.py            NewsBot orchestrator (image + video pipelines)
├── scheduler.py       Async scheduler — fetch, post, video_fetch, video_post,
│                      cache_clean cycles + daily analytics window
├── config.json        All knobs (sources, categories, image, video_bot, cache)
├── requirements.txt   Pip dependency list (used by setup.sh on VPS)
├── pyproject.toml     uv / pip metadata (used by Replit)
├── setup.sh           One-shot Ubuntu/Debian VPS installer
├── news-bot.service   systemd unit for 24/7 background running
├── .env.example       Template for secrets (FB token, Gemini key, …)
│
├── collectors/        Async RSS fetcher (+HTML fallback), dedup, trending scorer
├── ai/                Bangla summarizer (Gemini) + EN→BN translator
├── poster/            Facebook Graph API
├── image_gen/         Pillow 1080×1080 image generator
│   └── bangla_renderer.py  HarfBuzz (uharfbuzz) + FreeType (freetype-py) shaper
│                            for proper Bangla conjuncts & vowel-sign placement
├── video/             Video News Bot
│   ├── video_collector.py    Wikimedia / Internet Archive / Pexels / Pixabay / VOA
│   ├── video_processor.py    aiohttp download + ffmpeg watermark
│   ├── video_poster.py       Facebook Graph /videos endpoint
│   └── video_orchestrator.py Translate → process → post pipeline w/ dedup store
├── utils/             cache_cleaner, logger, config_loader, storage, analytics
├── assets/fonts/      NotoSansBengali-Bold.ttf (downloaded by setup.sh)
├── data/              Runtime: images/, videos/, posted.json, events.jsonl
└── logs/              Rotating news_bot.log
```

## Runtime

- Workflow `News Bot` runs `uv run python main.py` as a background process on Replit.
- Logs: `logs/news_bot.log` (rotating 5 MB × 5 backups).
- Image posts: `data/images/news_<category>_<ts>.jpg`.
- Video posts: `data/videos/`.
- Posted-article cache: `data/posted.json`; video dedup: `posted_videos.json`.
- Daily report: `data/report_YYYY-MM-DD.json` (23:55 Asia/Dhaka).

## Image post design

- Top: bold dark ribbon with the **single-line headline**.
- Just below ribbon: small category badge.
- Center: 3-line summary body with engagement hook line.
- Footer: source name → date • brand → "BOT BY TOHIDUL".

## Video post design

- Top dark ribbon containing the translated Bangla headline,
- Bottom strip with `Credit: <source> • <license>`,
- Small `BOT BY TOHIDUL` brand stamp,
- Capped to 90 s / 1080p / 30 fps for Facebook video limits.

## Cache cleaner

Runs every `scheduler.cache_clean_interval_minutes` (default 60). For each
configured directory it deletes files older than the TTL, then enforces a
max-size cap. `events.jsonl` is rotated to `events.jsonl.old`.

## Configuration

All non-secret tunables: `config.json`. Secrets (Facebook page token + page
id, Gemini key, optional Pexels / Pixabay keys) live in the `credentials`
block of `config.json` (or `.env`).

## Dependencies

- Python 3.11 (managed by `uv` on Replit; standard `venv` on VPS).
- Pip packages (see `requirements.txt`): aiohttp, feedparser, beautifulsoup4,
  lxml, requests, Pillow, uharfbuzz, freetype-py, python-dotenv,
  google-generativeai, openai, schedule, pytz, deep-translator, yt-dlp.
- System: ffmpeg + ffprobe, Noto Bengali fonts, libjpeg/zlib/freetype/
  harfbuzz/fribidi headers (installed by `setup.sh`).

## Deployment on a VPS (Ubuntu 22.04+, Debian 12, etc.)

```bash
# 1. Clone or upload the project to /opt/news_bot
sudo mkdir -p /opt/news_bot && sudo chown $USER:$USER /opt/news_bot
git clone <your-repo> /opt/news_bot      # or scp/rsync your files
cd /opt/news_bot

# 2. One-shot installer (system pkgs + venv + pip deps + font + .env)
bash setup.sh

# 3. Edit secrets
nano .env                                 # or: nano config.json

# 4. Quick test
.venv/bin/python main.py                  # Ctrl+C to stop

# 5. Install as a 24/7 systemd service
sudo cp news-bot.service /etc/systemd/system/
sudo sed -i "s|/opt/news_bot|$PWD|g" /etc/systemd/system/news-bot.service
sudo sed -i "s|User=newsbot|User=$USER|g; s|Group=newsbot|Group=$USER|g" /etc/systemd/system/news-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot
sudo journalctl -u news-bot -f            # live logs
```

`setup.sh` installs everything required so `pip install` does not fail on
common VPS images: `python3.11`, `python3.11-venv`, build-essential,
`libjpeg-dev`, `zlib1g-dev`, `libfreetype6-dev`, `libharfbuzz-dev`,
`libfribidi-dev`, `libxml2-dev`, `libxslt1-dev`, `ffmpeg`, and the Noto
font family.

On Replit the `News Bot` workflow keeps the bot alive while the workspace is
open; for always-on hosting use the deployment flow.
