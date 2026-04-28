# AI News Summary Bot (Bangla)

Production-ready Python 3.11 bot that fetches Bangladeshi news from RSS feeds,
summarizes it in Bangla using Gemini/OpenAI, generates a 1080×1080 post image,
and publishes to Facebook Page, Telegram channel, and (optionally) WordPress.

## Architecture

```
news_bot/
├── collectors/      Async RSS fetcher (+HTML fallback), dedup, trending scorer
├── ai/              Bangla summarizer (Gemini/OpenAI) + EN→BN translator
├── poster/          Facebook Graph API, Telegram Bot API, WordPress REST API
├── image_gen/       Pillow-based 1080×1080 brand-aware image generator
├── utils/           Logger (rotating files), config loader, JSON storage, analytics
├── main.py          NewsBot orchestrator + entrypoint
├── scheduler.py     Async scheduler (4 daily windows + instant breaking news)
├── config.json      All knobs (sources, categories, scheduling, image, etc.)
├── .env.example     API keys template
├── setup.sh         One-shot Ubuntu installer
└── news-bot.service systemd unit
```

## Runtime

- Workflow `News Bot` runs `python -m news_bot.main` as a background console process.
- Bot writes rotating logs to `news_bot/logs/news_bot.log` (5 MB × 5 backups).
- Generated images saved to `news_bot/data/images/`.
- Posted-article cache: `news_bot/data/posted.json` (TTL 48h).
- Daily analytics report: `news_bot/data/report_YYYY-MM-DD.json` (auto at 23:55 Asia/Dhaka).

## Configuration

All non-secret tunables live in `news_bot/config.json`. Secrets come from `.env`
(see `news_bot/.env.example`). Posting channels are off by default — set
`facebook.enabled`, `telegram.enabled`, or `wordpress.enabled` to `true` once
the matching env vars are populated.

## Dependencies

- Python 3.11
- pip: aiohttp, feedparser, beautifulsoup4, lxml, requests, Pillow,
  python-dotenv, google-generativeai, openai, schedule, pytz, deep-translator
- System: noto-fonts (for Bangla glyph rendering)
- Bundled font: `news_bot/assets/fonts/NotoSansBengali-Bold.ttf`

## Deployment

For 24/7 hosting on Ubuntu 22.04+ VPS, see `news_bot/README.md` (full
quickstart with `setup.sh` and `news-bot.service`).
