"""One-shot test command for the Video News Bot.

Usage:
    python test_video.py           # collect + post 1 video to FB
    python test_video.py --dry-run # collect + process, but do NOT post

What it does:
    1. Loads config.json (with secrets resolved from env)
    2. Spins up a VideoBot instance in isolation (no scheduler, no news bot)
    3. Runs ONE fetch_cycle to populate the queue
    4. Runs ONE post_cycle to publish a single video (or skips publish in --dry-run)
    5. Prints a clean summary and exits

Use this to verify the video pipeline end-to-end without waiting for the
scheduler's 3-hour interval.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from utils.config_loader import load_config
from utils.logger import get_logger, setup_logging
from video.video_orchestrator import VideoBot

log = get_logger("news_bot.test_video")


async def amain(dry_run: bool) -> int:
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
    # Force-enable for the test even if disabled in config
    video_cfg["enabled"] = True
    # Always post just one video in the test, no matter the config value
    video_cfg["max_posts_per_run"] = 1

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
    log.info("FB ready:       %s", bot.poster.is_ready())
    log.info("Translate→bn:   %s", bot.translate_to_bn)
    log.info("─" * 60)

    # 1) Fetch
    await bot.fetch_cycle()
    log.info("Queue size after fetch: %d", len(bot.queue))

    if not bot.queue:
        log.error("❌ No video items collected — check internet / source config")
        return 2

    # Print a quick preview of the top candidate
    top = bot.queue[0]
    log.info("Top candidate:")
    log.info("  • Title:    %s", top.title[:100])
    log.info("  • Source:   %s", top.source)
    log.info("  • License:  %s", top.license_name)
    log.info("  • Author:   %s", top.author or "—")
    log.info("  • Duration: %ss", top.duration_seconds)
    log.info("  • URL:      %s", top.video_url[:120])

    if dry_run:
        # Process only, no publish
        async with bot._lock:
            item = bot.queue[0]
        headline = item.title
        if bot.translator and VideoBot._is_mostly_english(item.title):
            translated = bot.translator.translate(item.title)
            if translated:
                headline = translated
        log.info("🎬 Dry-run: processing video only (no FB upload)")
        out_path = await bot.processor.process(item, headline)
        if out_path:
            log.info("✅ Dry-run OK — processed file: %s", out_path)
            log.info("    (file kept for manual inspection)")
            return 0
        log.error("❌ Dry-run failed — processor returned no output")
        return 3

    # 2) Post one
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
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + process the top video but do NOT upload to Facebook.",
    )
    args = parser.parse_args()
    rc = asyncio.run(amain(dry_run=args.dry_run))
    sys.exit(rc)


if __name__ == "__main__":
    main()
