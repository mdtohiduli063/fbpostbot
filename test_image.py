"""One-shot test command for the Image (text) News Bot pipeline.

Usage:
    python test_image.py                # collect → summarize → render → post 1 image to FB
    python test_image.py --dry-run      # do everything EXCEPT the FB upload (image kept on disk)
    python test_image.py --count 3      # post up to 3 images in this run
    python test_image.py --category breaking   # only consider articles in a given category
    python test_image.py --list-sources        # just print the configured RSS sources and exit

What it does:
    1. Loads config.json (with secrets resolved from env)
    2. Spins up the same NewsBot orchestrator the scheduler uses, but runs ONLY
       a single fetch + post cycle (no scheduler loop, no video bot, no cleaner).
    3. Prints a clean human-readable summary at the end and exits.

Use this to verify the image / text pipeline end-to-end without waiting
for the scheduler.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import List, Tuple

from utils.config_loader import load_config
from utils.logger import get_logger, setup_logging

log = get_logger("news_bot.test_image")


def _print_sources(cfg: dict) -> None:
    sources = cfg["collection"]["sources"]
    print()
    print("─" * 70)
    print(" Configured RSS / news sources")
    print("─" * 70)
    for i, s in enumerate(sources, 1):
        flag = "✓" if s.get("enabled", True) else "✗"
        print(f"  [{flag}] {i:>2}. {s['name']:<25} {s['url']}")
    print("─" * 70)
    enabled = sum(1 for s in sources if s.get("enabled", True))
    print(f" Total: {enabled} enabled / {len(sources)} configured")
    print()


async def amain(dry_run: bool, count: int, category_filter: str | None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, "config.json")
    cfg = load_config(cfg_path)

    setup_logging(
        logs_dir=os.path.join(here, cfg["general"]["logs_dir"]),
        level=cfg["logging"]["level"],
        max_bytes=cfg["logging"]["max_bytes"],
        backup_count=cfg["logging"]["backup_count"],
    )

    cfg["general"]["data_dir"] = os.path.join(here, cfg["general"]["data_dir"])
    cfg["general"]["logs_dir"] = os.path.join(here, cfg["general"]["logs_dir"])
    if cfg["general"].get("page_logo_path"):
        cfg["general"]["page_logo_path"] = os.path.join(here, cfg["general"]["page_logo_path"])

    # Disable the video bot for this test (we only test the image pipeline)
    cfg.setdefault("video_bot", {})["enabled"] = False
    # Force realtime OFF — we'll publish manually so we control the count
    cfg["scheduler"]["realtime_mode"] = False
    cfg["scheduler"]["instant_breaking_news"] = False

    # Lazy import after config tweaks (so VideoBot init is cheap)
    from main import NewsBot

    bot = NewsBot(cfg)

    log.info("─" * 60)
    log.info("🖼  IMAGE BOT TEST RUN")
    log.info("Dry-run:        %s", dry_run)
    log.info("FB ready:       %s", bot.fb.is_ready())
    log.info("Posts to make:  %d", count)
    log.info("Category filter: %s", category_filter or "(none)")
    log.info("─" * 60)

    # 1) Fetch + rank
    await bot.fetch_cycle()
    queue: List[Tuple] = list(bot.queue)
    if category_filter:
        queue = [q for q in queue if q[2] == category_filter]
        bot.queue = queue

    log.info("Queue size after fetch: %d", len(queue))
    if not queue:
        log.error("❌ Nothing in queue — try without --category, or check internet.")
        return 2

    # Preview top candidates
    log.info("Top candidates:")
    for i, (art, score, cat) in enumerate(queue[:max(count, 5)], 1):
        log.info("  %d. [%s | %.1f] %s — %s", i, cat, score, art.title[:80], art.source)

    # 2) Publish (or dry-run)
    if dry_run:
        log.info("🖼  Dry-run: rendering image without FB upload")
        # Disable FB so _publish_one only renders + saves the image
        bot.fb.access_token = ""
        bot.fb.page_id = ""

    posted = 0
    for art, score, cat in queue[:count]:
        try:
            ok = await bot._publish_one(art, score, cat)
            if ok:
                posted += 1
        except Exception as e:
            log.exception("Publish failed for '%s': %s", art.title[:60], e)

    if dry_run:
        log.info("✅ Dry-run done — %d image(s) generated.", posted)
        log.info("    Inspect them in: %s", os.path.join(cfg["general"]["data_dir"], "images"))
        # Don't auto-delete in dry-run
    else:
        log.info("✅ Test complete — %d image(s) posted to Facebook.", posted)

    return 0 if posted else 3


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a single image (text) bot test cycle."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Render the image(s) but do NOT upload to Facebook.",
    )
    parser.add_argument(
        "--count", type=int, default=1,
        help="How many top-ranked articles to publish (default 1).",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Only consider articles in this category (eg. breaking, politics, cricket).",
    )
    parser.add_argument(
        "--list-sources", action="store_true",
        help="Print configured RSS sources and exit.",
    )
    args = parser.parse_args()

    if args.list_sources:
        here = os.path.dirname(os.path.abspath(__file__))
        cfg = load_config(os.path.join(here, "config.json"))
        _print_sources(cfg)
        return

    rc = asyncio.run(amain(
        dry_run=args.dry_run,
        count=max(1, args.count),
        category_filter=args.category,
    ))
    sys.exit(rc)


if __name__ == "__main__":
    main()
