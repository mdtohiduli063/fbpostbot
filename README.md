# 🇧🇩 AI News Page Bot — Bangla Facebook Page Auto-Poster

Production-ready Python 3.11 bot that fetches Bangladeshi news from RSS feeds,
summarizes it in clean Bangla using **Gemini**, generates a 1080×1080 post
image, and publishes to your **Facebook Page** automatically — 24/7.
Also has a **video pipeline** that pulls copyright-free / fair-use clips and
posts them with proper attribution.

---

## ✨ Features

- 7 Bangla news sources out of the box (Prothom Alo, BBC Bangla, BDnews24,
  Jugantor, Daily Star Bangla, Bonik Barta, DW Bangla) — easy to add more.
- Async RSS fetcher with HTML scrape fallback.
- Smart deduplication (URL hash + normalized-title hash, persistent).
- Trending/viral scoring using configurable Bangla keywords + recency boost.
- Gemini-powered Bangla summarizer → headline + 2–4 line summary + hashtags.
- **Smart fallback summarizer** (sentence extraction + category intro)
  when Gemini quota runs out — body never duplicates the headline.
- Auto English→Bangla translation for foreign sources.
- 1080×1080 image generator with category-aware gradients & Bangla shaping
  (HarfBuzz + FreeType for proper conjuncts).
- Video pipeline (Wikimedia / Internet Archive / VOA / Pexels / Pixabay /
  YouTube via yt-dlp) with ffmpeg watermarking.
- Realtime mode (every 2 min poll, every new article posted instantly,
  throttled by `min_seconds_between_posts`).
- Auto cache cleaner (TTL + size cap on images / videos / logs / events).
- Rotating logs + daily JSON analytics report.

---

## 📁 Project structure (flat, root-level)

```
.
├── main.py                # Entrypoint — runs the full bot (image + video + scheduler)
├── cli.py                 # Unified CLI: run / test / sources / status
├── test_image.py          # One-shot image-pipeline test
├── test_video.py          # One-shot video-pipeline test
├── scheduler.py           # Async time-based scheduler
├── config.json            # All settings + credentials in one place
├── requirements.txt       # Pip deps (used by setup.sh)
├── pyproject.toml         # uv / pip metadata
├── setup.sh               # One-shot Ubuntu/Debian VPS installer
├── news-bot.service       # systemd unit
│
├── collectors/            # RSS fetcher + dedup + trending scorer
├── ai/                    # Gemini summarizer + EN→BN translator
├── poster/                # Facebook Graph API poster
├── image_gen/             # Pillow + HarfBuzz Bangla image generator
├── video/                 # Video collector / processor / poster / orchestrator
├── utils/                 # logger, config loader, storage, analytics, cache cleaner
├── assets/fonts/          # NotoSansBengali-Bold.ttf (downloaded by setup.sh)
├── data/                  # posted-cache, generated images/videos, daily reports
└── logs/                  # rotating log files
```

---

## 🚀 Quickstart on Ubuntu 22.04+ / Debian 12 VPS

```bash
git clone <your-repo> /opt/news_bot
cd /opt/news_bot
nano config.json             # paste FB token, page id, Gemini key (credentials block)
bash setup.sh                # ✅ installs everything AND starts the bot
#   bash setup.sh --install-only   # install only, don't auto-start
#   bash run.sh                    # start later (auto-uses .venv)
```

Run as a 24/7 background service (the `setup.sh` output prints the exact
sed commands you need so paths/user are auto-substituted):

```bash
sudo cp news-bot.service /etc/systemd/system/
sudo sed -i "s|/opt/news_bot|$PWD|g" /etc/systemd/system/news-bot.service
sudo sed -i "s|User=newsbot|User=$USER|g; s|Group=newsbot|Group=$USER|g" \
    /etc/systemd/system/news-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot
sudo journalctl -u news-bot -f       # follow logs
```

---

## 🧪 Test commands (run before / instead of full bot)

Use these to verify pieces of the pipeline in isolation. They reuse exactly
the same code path the real bot does — no mocks.

### 🖼  Image (text) pipeline

```bash
# Render + post 1 top article to Facebook
python test_image.py

# Just render the image (NO Facebook upload, file kept on disk)
python test_image.py --dry-run

# Post top 3 articles in this run
python test_image.py --count 3

# Only consider articles in a specific category
python test_image.py --category breaking
python test_image.py --category cricket --dry-run

# Show all configured RSS news sources & exit
python test_image.py --list-sources
```

### 🎬 Video pipeline

```bash
# Fetch + watermark + upload 1 video to Facebook
python test_video.py

# Fetch + watermark only (no upload)
python test_video.py --dry-run

# Show every video source + which API keys are loaded
python test_video.py --list-sources

# Restrict to ONE source (great for debugging a specific channel)
python test_video.py --source wikimedia
python test_video.py --source internet_archive
python test_video.py --source youtube
python test_video.py --source pexels --dry-run

# Post up to N videos
python test_video.py --count 2

# In dry-run, KEEP the processed file for manual inspection
python test_video.py --dry-run --keep
```

### 🧰 Unified CLI (same thing, shorter typing)

```bash
python cli.py run                        # = python main.py
python cli.py test image --dry-run       # = python test_image.py --dry-run
python cli.py test video --source youtube
python cli.py sources image              # list RSS sources
python cli.py sources video              # list video sources + API key status
python cli.py status                     # disk usage, queue size, posted counts
```

### 🎬 Where the videos come from

| Source key         | Where                                                  | License model                          | Needs API key?            |
|--------------------|--------------------------------------------------------|----------------------------------------|---------------------------|
| `voa`              | Voice of America RSS feeds                             | US Federal Government → Public Domain  | no (off by default)       |
| `wikimedia`        | Wikimedia Commons category search                      | CC-BY / CC-BY-SA / CC0 / PD            | no                        |
| `internet_archive` | archive.org news collections                           | PD + Creative Commons                  | no                        |
| `pexels`           | pexels.com/videos                                      | Pexels License (free w/ attribution)   | yes (`pexels_api_key`)    |
| `pixabay`          | pixabay.com/videos                                     | Pixabay Content License (free w/ attr) | yes (`pixabay_api_key`)   |
| `youtube`          | Bangla news channels via `yt-dlp` (Jamuna TV, Somoy TV)| Editorial / fair-use, full credit      | no                        |

Edit `config.json → video_bot.youtube.channels[]` to add your own channels,
or `config.json → video_bot.search_terms[]` to change what the bot searches
on Wikimedia / Internet Archive / Pexels / Pixabay.

---

## 🔑 Credentials (inside `config.json`)

```json
"credentials": {
  "gemini_api_key": "AIza…",
  "openai_api_key": "",
  "facebook_page_id": "1066110556588827",
  "facebook_page_access_token": "EAAK…",
  "pexels_api_key": "",
  "pixabay_api_key": ""
}
```

| Key                            | Where to get it                                                   |
|--------------------------------|-------------------------------------------------------------------|
| `gemini_api_key`               | https://aistudio.google.com/app/apikey                            |
| `facebook_page_id`             | Page → Settings → About → Page ID                                 |
| `facebook_page_access_token`   | Graph API Explorer → exchange to long-lived **Page** token        |
| `pexels_api_key` (optional)    | https://www.pexels.com/api/                                       |
| `pixabay_api_key` (optional)   | https://pixabay.com/api/docs/                                     |

> ⚠️ `config.json` is the **only** place credentials live (no `.env` file).
> It contains real tokens, so add it to `.gitignore` before pushing this
> repo anywhere public.

---

## ⚙️ Common config tweaks

- `collection.fetch_interval_minutes` — RSS poll cadence (default 2)
- `collection.sources[]` — add/remove RSS feeds, each can be `enabled: false`
- `scheduler.realtime_mode` — instant publish on every fetch (default true)
- `scheduler.min_seconds_between_posts` — throttle between two posts
- `scheduler.max_posts_per_fetch` — max posts per fetch cycle
- `scheduler.delete_image_after_post` — free disk after each successful post
- `categories.*` — toggle whole topics on/off
- `viral_keywords.*` — tune what counts as breaking/political/cricket/etc.
- `image.brand_name` — footer text shown on every image
- `video_bot.search_terms` — what to search on Wikimedia/IA/Pexels/Pixabay
- `video_bot.youtube.channels[]` — Bangla YouTube news channels for clips
- `cache.*` — TTL + size cap for images / videos / logs / events

---

## 🪵 Logs & analytics

- Rotating log file: `logs/news_bot.log` (5 MB × 5 backups)
- Append-only event log: `data/events.jsonl`
- Daily JSON report: `data/report_YYYY-MM-DD.json` (23:55 local)
- `python cli.py status` — quick snapshot of disk, queue, posted counts

---

## 🛟 Troubleshooting

| Symptom                              | Likely cause / fix                                         |
|--------------------------------------|------------------------------------------------------------|
| `pip install` fails on Pillow/lxml   | Run `bash setup.sh` first — it installs all build headers  |
| Image shows boxes instead of Bangla  | `assets/fonts/NotoSansBengali-Bold.ttf` missing            |
| `Facebook publish failed`            | Token expired or page id mismatch                          |
| First-comment 403                    | Token missing `pages_manage_engagement` permission         |
| `LLM call failed` / quota 429        | Bot auto-falls-back to sentence-extraction (still good)    |
| Same news posts twice                | `data/posted.json` was deleted — it's the dedup cache      |
| Video bot collects 0 items           | `python test_video.py --list-sources` to verify config     |
| `ffmpeg not found`                   | `sudo apt-get install -y ffmpeg`                           |

---

## 📜 License

MIT — do whatever you want, just don't use it to spread misinformation.
