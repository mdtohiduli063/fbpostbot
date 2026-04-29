"""One-shot test command for the Video News Bot.

Usage:
    python test_video.py                       # collect + post 1 video to FB
    python test_video.py --dry-run             # collect + process, but do NOT post
    python test_video.py --list-sources        # show all video sources & their status
    python test_video.py --source wikimedia    # only use ONE source (voa, wikimedia,
                                               #   internet_archive, pexels, pixabay, youtube)
    python test_video.py --count 2             # post up to N videos (default 1)
    python test_video.py --keep                # in dry-run, keep the processed file

Video sources (default, free / public-domain):
    • Wikimedia Commons       — CC-BY / CC-BY-SA / Public Domain
    • Internet Archive        — Public Domain & Creative Commons
    • Voice of America (VOA)  — US Federal Government → Public Domain
    • Pexels videos           — Pexels License (needs PEXELS_API_KEY)
    • Pixabay videos          — Pixabay Content License (needs PIXABAY_API_KEY)
    • YouTube channels        — Editorial / fair-use clips from configured Bangla
                                news channels (Jamuna TV, Somoy TV, etc.) using
                                yt-dlp; controlled by config.json → video_bot.youtube
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from utils.config_loader import load_config
from utils.logger import get_logger, setup_logging

log = get_logger("news_bot.test_video")

ALL_SOURCES = ["voa", "wikimedia", "internet_archive", "pexels", "pixabay", "youtube"]


def _print_sources(cfg: dict) -> None:
    vb = cfg.get("video_bot", {})
    enabled = vb.get("sources_enabled", {})
    secrets = cfg.get("secrets", {}) or cfg.get("credentials", {})

    print()
    print("─" * 72)
    print(" 🎬 Configured VIDEO sources (where the bot pulls clips from)")
    print("─" * 72)
    rows = [
        ("voa",              "Voice of America (Public Domain)",         None),
        ("wikimedia",        "Wikimedia Commons (CC / PD)",              None),
        ("internet_archive", "Internet Archive (PD / CC)",               None),
        ("pexels",           "Pexels videos",                            "pexels_api_key"),
        ("pixabay",          "Pixabay videos",                           "pixabay_api_key"),
        ("youtube",          "YouTube editorial channels (yt-dlp)",      None),
    ]
    for key, label, secret_key in rows:
        on = enabled.get(key, True)
        flag = "✓ ON " if on else "✗ off"
        note = ""
        if secret_key:
            has_key = bool(secrets.get(secret_key))
            note = f"   (key: {'set' if has_key else 'MISSING'})"
        print(f"  [{flag}]  {key:<18} — {label}{note}")
    print("─" * 72)

    yt = vb.get("youtube", {})
    if yt.get("enabled", True):
        chans = yt.get("channels", [])
        print(f" YouTube channels ({len(chans)} configured):")
        for ch in chans:
            print(f"    • {ch.get('name','?'):<22} {ch.get('url','')}")
        print(f"   max/channel={yt.get('max_per_channel',2)}  "
              f"segment={yt.get('segment_seconds',15)}s  "
              f"max_segment={yt.get('max_segment_seconds',60)}s")
    print()
    terms = vb.get("search_terms", [])
    if terms:
        print(f" Search terms used for Wikimedia/IA/Pexels/Pixabay:")
        print(f"   {', '.join(terms)}")
    print()


async def amain(dry_run: bool, count: int, only_source: str | None, keep: bool) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, "config.json")
    cfg = load_config(cfg_path)

    setup_logging(
        logs_dir=os.path.join(here, cfg["general"]["logs_dir"]),
        level=cfg["logging"]["level"],
        max_bytes=cfg["logging"]["max_bytes"],
        backup_count=cfg["logging"]["backup_count"],
    )

    data_dir = os.path.join(here, cfg["general"]["data_dir"])
    os.makedirs(data_dir, exist_ok=True)

    video_cfg = dict(cfg.get("video_bot", {}))
    video_cfg["enabled"] = True
    video_cfg["max_posts_per_run"] = count

    # Optionally restrict to one source
    if only_source:
        if only_source not in ALL_SOURCES:
            log.error("❌ Unknown source '%s'. Choose from: %s",
                      only_source, ", ".join(ALL_SOURCES))
            return 5
        new_enabled = {s: (s == only_source) for s in ALL_SOURCES}
        video_cfg["sources_enabled"] = new_enabled
        log.info("🔒 Restricted to source: %s", only_source)

    # Lazy import to honour the patched config
    from video.video_orchestrator import VideoBot

    bot = VideoBot(
        cfg=video_cfg,
        secrets=cfg["secrets"],
        data_dir=data_dir,
        fb_credit=cfg["general"].get("bot_credit", "BOT BY TOHIDUL"),
        brand_name=cfg["general"].get("brand_name", "News Summary"),
        font_path=cfg["general"].get("font_path"),
    )

    log.info("─" * 60)
    log.info("🎬 VIDEO BOT TEST RUN")
    log.info("Dry-run:        %s", dry_run)
    log.info("Count:          %d", count)
    log.info("FB ready:       %s", bot.poster.is_ready())
    log.info("Translate→bn:   %s", bot.translate_to_bn)
    log.info("Source filter:  %s", only_source or "(all enabled)")
    log.info("─" * 60)

    # 1) Fetch
    await bot.fetch_cycle()
    log.info("Queue size after fetch: %d", len(bot.queue))

    if not bot.queue:
        log.error("❌ No video items collected — check internet, source config, "
                  "or use --list-sources to inspect setup.")
        return 2

    # Print preview of all collected candidates
    log.info("Candidates:")
    for i, v in enumerate(bot.queue[:max(count, 5)], 1):
        log.info("  %d. [%s | %s] %s (%ss)",
                 i, v.source, v.license_name, v.title[:80], v.duration_seconds)

    if dry_run:
        async with bot._lock:
            item = bot.queue[0]
        headline = item.title
        if bot.translator and VideoBot._is_mostly_english(item.title):
            t = bot.translator.translate(item.title)
            if t:
                headline = t
        log.info("🎬 Dry-run: processing top video only (no FB upload)")
        out_path = await bot.processor.process(item, headline)
        if out_path:
            log.info("✅ Dry-run OK — processed file: %s", out_path)
            if keep:
                log.info("   (file kept for manual inspection)")
            else:
                try:
                    if os.path.isfile(out_path):
                        os.remove(out_path)
                        log.info("   (file deleted; pass --keep to retain it)")
                except Exception:
                    pass
            return 0
        log.error("❌ Dry-run failed — processor returned no output")
        return 3

    # 2) Real post
    if not bot.poster.is_ready():
        log.error("❌ Facebook not configured — cannot post. "
                  "Set FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN, "
                  "or use --dry-run.")
        return 4

    await bot.post_cycle()
    log.info("✅ Video bot test completed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single video bot test cycle.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + process the top video but do NOT upload to Facebook.")
    parser.add_argument("--count", type=int, default=1,
                        help="How many videos to post (default 1).")
    parser.add_argument("--source", type=str, default=None,
                        help=f"Restrict to one source: {', '.join(ALL_SOURCES)}.")
    parser.add_argument("--keep", action="store_true",
                        help="In --dry-run, keep the processed file (default deletes it).")
    parser.add_argument("--list-sources", action="store_true",
                        help="Print configured video sources and exit.")
    args = parser.parse_args()

    if args.list_sources:
        here = os.path.dirname(os.path.abspath(__file__))
        cfg = load_config(os.path.join(here, "config.json"))
        _print_sources(cfg)
        return

    rc = asyncio.run(amain(
        dry_run=args.dry_run,
        count=max(1, args.count),
        only_source=args.source,
        keep=args.keep,
    ))
    sys.exit(rc)


if __name__ == "__main__":
    main()
