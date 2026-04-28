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

## Architecture

```
news_bot/
├── collectors/        Async RSS fetcher (+HTML fallback), dedup, trending scorer
├── ai/                Bangla summarizer (Gemini) + EN→BN translator
├── poster/            Facebook Graph API, Telegram, WordPress
├── image_gen/         Pillow 1080×1080 image generator — top single-line ribbon
│                      headline + category badge + body + engagement hook + footer
│   └── bangla_renderer.py  HarfBuzz (uharfbuzz) + FreeType (freetype-py) shaper
│                            — proper Bangla conjuncts & vowel-sign placement,
│                            because the prebuilt Pillow wheels don't ship libraqm
├── video/             NEW Video News Bot
│   ├── video_collector.py    Wikimedia / Internet Archive / Pexels / Pixabay / VOA
│   ├── video_processor.py    aiohttp download + ffmpeg watermark (top headline
│   │                         ribbon, bottom credit line, brand stamp)
│   ├── video_poster.py       Facebook Graph /videos endpoint
│   └── video_orchestrator.py Translate → process → post pipeline w/ dedup store
├── utils/
│   ├── cache_cleaner.py      NEW TTL + size-cap pruner for images/videos/reports
│   │                         /events/logs (rotates events.jsonl with .old suffix)
│   ├── logger.py, config_loader.py, storage.py, analytics.py
├── main.py            NewsBot orchestrator (image + video pipelines)
├── scheduler.py       Async scheduler — fetch, post, video_fetch, video_post,
│                      cache_clean cycles + daily analytics window
└── config.json        All knobs (sources, categories, image, video_bot, cache)
```

## Runtime

- Workflow `News Bot` runs `uv run python -m news_bot.main` as a background process.
- Logs: `news_bot/logs/news_bot.log` (rotating 5 MB × 5 backups).
- Image posts: `news_bot/data/images/news_<category>_<ts>.jpg`.
- Video posts: `news_bot/data/videos/` (download + watermarked output).
- Posted-article cache: `news_bot/data/posted.json`; video dedup: `posted_videos.json`.
- Daily report: `news_bot/data/report_YYYY-MM-DD.json` (23:55 Asia/Dhaka).

## Image post design

- Top: bold dark ribbon with the **single-line headline** (auto-shrinks down to
  22 px before truncating with an ellipsis).
- Just below ribbon: small category badge (Bangla label, no emoji because
  the bundled Bangla font has no color-emoji glyphs).
- Center: 3-line summary body, centered, with engagement hook line below.
- Footer: source name → "28 Apr 2026 • News Summary" → "BOT BY TOHIDUL".

## Video post design

Each posted video is the original clip:

- topped with a dark ribbon containing the translated Bangla headline,
- a bottom strip with `Credit: <source> • <license>`,
- a small `BOT BY TOHIDUL` brand stamp,
- and capped to 90 s / 1080p / 30 fps so it fits Facebook video limits.

The Facebook caption opens with a hook line, the Bangla summary, the original
title, the source URL, the license, and `#NewsBot #Bangladesh` tags.

## Cache cleaner

Runs every `scheduler.cache_clean_interval_minutes` (default 60). For each
configured directory (`images/`, `videos/`, reports, logs) it deletes files
older than the TTL, then enforces a max-size cap by deleting the oldest
remaining files. `events.jsonl` is rotated to `events.jsonl.old` (keeping
N archives) when it exceeds its size cap.

## Configuration

All non-secret tunables: `news_bot/config.json` (`cache`, `video_bot`,
`scheduler.video_post_interval_minutes`, `scheduler.cache_clean_interval_minutes`).
Secrets (Facebook page token + page id, Gemini key, optional Pexels /
Pixabay keys) live in the `credentials` block of `config.json` (or `.env`).
VOA feeds are disabled by default because the public RSS endpoints
currently 404; Wikimedia + Internet Archive are the active video sources.

## Dependencies

- Python 3.11 managed via `uv` (`pyproject.toml`).
- pip: aiohttp, feedparser, beautifulsoup4, lxml, requests, Pillow,
  uharfbuzz, freetype-py, python-dotenv, google-generativeai, schedule,
  pytz, deep-translator.
- System: ffmpeg + ffprobe (Nix), Noto Bengali fonts.
- Bundled font: `news_bot/assets/fonts/NotoSansBengali-Bold.ttf`.

## Deployment

24/7 hosting notes for Ubuntu 22.04+ VPS in `news_bot/README.md`
(`setup.sh` + `news-bot.service`). On Replit the `News Bot` workflow keeps
it alive while the workspace is open; for always-on use the deployment flow.
