# 🇧🇩 AI News Summary Bot

Fully automated 24/7 bot that collects trending Bangladeshi news, summarizes it
in clean readable Bangla using Gemini/OpenAI, generates a 1080×1080 post image,
and publishes to **Facebook Page**, **Telegram channel**, and (optionally)
**WordPress**.

---

## ✨ Features

| Module                    | What it does                                                       |
|---------------------------|--------------------------------------------------------------------|
| `collectors/rss_collector`| Async RSS + HTML scrape fallback (Prothom Alo, BBC Bangla, …)      |
| `collectors/deduplicator` | URL + normalized-title hashing, persistent across restarts         |
| `collectors/trending`     | Keyword + recency scoring → detects breaking/viral news            |
| `ai/summarizer`           | Gemini or OpenAI → Bangla headline + 2–4 line summary + hashtags   |
| `ai/translator`           | Auto English→Bangla translation for foreign sources                |
| `image_gen`               | Bangla-text image generation (1080×1080, brand-aware gradients)    |
| `poster/facebook`         | Graph API photo upload + auto first-comment with source link       |
| `poster/telegram`         | Telegram Bot API channel posting                                   |
| `poster/wordpress`        | REST API article + featured image upload                           |
| `scheduler`               | 4 daily slots (07:00 / 13:00 / 18:00 / 21:00) + instant breaking   |
| `utils/analytics`         | Append-only event log + daily JSON report                          |

---

## 📁 Project structure

```
news_bot/
├── collectors/        # news fetchers + dedup + trending scorer
├── ai/                # summarizer + translator
├── poster/            # Facebook / Telegram / WordPress
├── image_gen/         # Pillow-based image generator
├── utils/             # logger, config loader, storage, analytics
├── assets/fonts/      # drop NotoSansBengali-Bold.ttf here
├── data/              # posted-cache, generated images, daily reports
├── logs/              # rotating log files
├── main.py            # entrypoint
├── scheduler.py       # async time-based scheduler
├── config.json        # all knobs (no secrets)
├── .env.example       # API keys template
├── requirements.txt
├── setup.sh           # one-shot Ubuntu installer
└── news-bot.service   # systemd unit
```

---

## 🚀 Quickstart on Ubuntu 22.04+ VPS

```bash
git clone <your-repo> /opt/news_bot
cd /opt/news_bot/news_bot
bash setup.sh                # installs Python, deps, font, creates venv
nano .env                    # fill in API keys
.venv/bin/python -m news_bot.main   # smoke test (Ctrl+C to stop)
```

Run as a 24/7 service:

```bash
sudo cp news-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot
sudo journalctl -u news-bot -f       # follow logs
```

---

## 🔑 Required API keys (`.env`)

| Key                              | Where to get it                                               |
|----------------------------------|---------------------------------------------------------------|
| `GEMINI_API_KEY`                 | https://aistudio.google.com/app/apikey                        |
| `OPENAI_API_KEY` (alt)           | https://platform.openai.com/api-keys                          |
| `FACEBOOK_PAGE_ACCESS_TOKEN`     | Graph API Explorer → exchange to long-lived Page token        |
| `FACEBOOK_PAGE_ID`               | Page Settings → About → Page ID                               |
| `TELEGRAM_BOT_TOKEN`             | Talk to [@BotFather](https://t.me/BotFather)                  |
| `TELEGRAM_CHANNEL_ID`            | `@yourchannel` or numeric `-100…` (bot must be channel admin) |
| `WORDPRESS_*`                    | (optional) Users → Profile → Application Passwords            |

Then in `config.json` flip `enabled: true` for the channels you actually use.

---

## ⚙️ Configuration cheatsheet

`config.json` controls everything except secrets:

- `collection.fetch_interval_minutes` — how often to crawl RSS (default 7)
- `collection.sources[]` — add/remove RSS feeds, each can be `enabled: false`
- `scheduler.post_times` — daily windows in **local time** (`Asia/Dhaka`)
- `scheduler.max_posts_per_run` — burst limit per window
- `categories.*` — toggle whole topics on/off
- `viral_keywords.*` — tune what counts as breaking/political/cricket/etc.
- `ai.provider` — `"gemini"` or `"openai"`
- `image.*` — colors, fonts, brand name, logo size

---

## 🧠 How it works (per cycle)

```
                ┌─ every 7 min ──────────────────────────────────────┐
                ▼                                                    │
  RSS sources → fetch → dedup → trending score → enqueue ────────────┘
                                       │
                                       ▼
                           ┌── if breaking & score≥5 ──┐
                           ▼                           ▼
        scheduled slot (07/13/18/21)            instant publish
                           │                           │
                           ▼                           ▼
            summarize (Gemini/OpenAI) → 1080×1080 image →
              Facebook + Telegram + (optional) WordPress
                           │
                           ▼
                  mark seen + analytics log
```

---

## 🪵 Logs & analytics

- Rotating log file: `logs/news_bot.log` (5 MB × 5 backups)
- Append-only event log: `data/events.jsonl`
- Daily JSON report: `data/report_YYYY-MM-DD.json`
  (auto-written at 23:55 local time)

---

## 🛟 Troubleshooting

| Symptom                              | Likely cause / fix                                     |
|--------------------------------------|--------------------------------------------------------|
| Image shows boxes instead of Bangla  | Drop `NotoSansBengali-Bold.ttf` into `assets/fonts/`   |
| `Facebook not configured`            | Set `facebook.enabled=true` AND env vars are populated |
| `LLM call failed`                    | Wrong/expired API key, quota, or network               |
| `Telegram post failed (400)`         | Bot is not admin in the channel                        |
| Same news posts twice                | `data/posted.json` was deleted — it's the dedup cache  |

---

## 📜 License

MIT — do whatever you want, just don't use it to spread misinformation.
