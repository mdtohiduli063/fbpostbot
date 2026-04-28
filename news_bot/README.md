# 🇧🇩 AI News Page Bot — Bangla Facebook Page Auto-Poster

Production-ready Python 3.11 bot that fetches Bangladeshi news from RSS feeds,
summarizes it in clean Bangla using **Gemini**, generates a 1080×1080 post
image, and publishes to your **Facebook Page** automatically — 24/7.

---

## ✨ Features

- 5 Bangla news sources out of the box (Prothom Alo, BBC Bangla, BDnews24,
  Jugantor, Daily Star Bangla) — easy to add more.
- Async RSS fetcher with HTML scrape fallback.
- Smart deduplication (URL hash + normalized-title hash, persistent across restarts).
- Trending/viral scoring using configurable Bangla keywords + recency boost.
- Gemini-powered Bangla summarizer → headline + 2–4 line summary + hashtags.
- Auto English→Bangla translation for foreign sources.
- 1080×1080 image generator with category-aware gradients & Bangla font.
- Scheduled posts at **07:00 / 13:00 / 18:00 / 21:00** Asia/Dhaka, plus instant
  breaking-news mode.
- Rotating logs + daily JSON analytics report.

---

## 📁 Project structure

```
news_bot/
├── collectors/        # RSS fetcher + dedup + trending scorer
├── ai/                # Gemini summarizer + EN→BN translator
├── poster/            # Facebook Graph API poster
├── image_gen/         # Pillow-based image generator
├── utils/             # logger, config loader, storage, analytics
├── assets/fonts/      # NotoSansBengali-Bold.ttf (bundled)
├── data/              # posted-cache, generated images, daily reports
├── logs/              # rotating log files
├── main.py            # entrypoint
├── scheduler.py       # async time-based scheduler
├── config.json        # ALL settings + credentials in one place
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
nano config.json             # paste your gemini key, fb page id + token
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

## 🔑 Credentials (inside `config.json`)

```json
"credentials": {
  "gemini_api_key": "AIza…",
  "facebook_page_id": "1066110556588827",
  "facebook_page_access_token": "EAAK…"
}
```

| Key                            | Where to get it                                                   |
|--------------------------------|-------------------------------------------------------------------|
| `gemini_api_key`               | https://aistudio.google.com/app/apikey                            |
| `facebook_page_id`             | Page → Settings → About → Page ID                                 |
| `facebook_page_access_token`   | Graph API Explorer → exchange to long-lived **Page** token        |

> ⚠️ `config.json` now contains real tokens. Add `news_bot/config.json` to
> `.gitignore` if you push this repo anywhere public.

---

## ⚙️ Common config tweaks

- `collection.fetch_interval_minutes` — how often to crawl RSS (default 7)
- `collection.sources[]` — add/remove RSS feeds, each can be `enabled: false`
- `scheduler.post_times` — daily windows in **local time** (`Asia/Dhaka`)
- `scheduler.max_posts_per_run` — burst limit per window
- `categories.*` — toggle whole topics on/off
- `viral_keywords.*` — tune what counts as breaking/political/cricket/etc.
- `image.brand_name` — footer text shown on every image
- `facebook.auto_first_comment` — only works if the token has
  `pages_manage_engagement` permission

---

## 🧠 Per-cycle pipeline

```
RSS sources → fetch → dedup → trending score → queue
                                              │
                       ┌──────────────────────┴─────┐
                       ▼                            ▼
            scheduled slot (07/13/18/21)     instant breaking
                       │                            │
                       ▼                            ▼
       Gemini summary → 1080×1080 image → Facebook Page
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
| Image shows boxes instead of Bangla  | `assets/fonts/NotoSansBengali-Bold.ttf` missing        |
| `Facebook publish failed`            | Token expired or page id mismatch                      |
| First-comment 403                    | Token missing `pages_manage_engagement` permission     |
| `LLM call failed`                    | Wrong/expired Gemini key, quota, or network            |
| Same news posts twice                | `data/posted.json` was deleted — it's the dedup cache  |

---

## 📜 License

MIT — do whatever you want, just don't use it to spread misinformation.
