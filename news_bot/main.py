"""Main entrypoint: wires collectors → AI → image gen → posters → scheduler."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any, Dict, List, Tuple

# Allow `python news_bot/main.py` AND `python -m news_bot.main`
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from news_bot.collectors.deduplicator import Deduplicator, article_key, title_key
    from news_bot.collectors.rss_collector import Article, RSSCollector
    from news_bot.collectors.trending import TrendingScorer
    from news_bot.ai.summarizer import Summarizer
    from news_bot.image_gen.image_generator import ImageGenerator
    from news_bot.poster.facebook import FacebookPoster
    from news_bot.poster.telegram import TelegramPoster
    from news_bot.poster.wordpress import WordPressPoster
    from news_bot.scheduler import Scheduler
    from news_bot.utils.analytics import Analytics
    from news_bot.utils.config_loader import load_config
    from news_bot.utils.logger import get_logger, setup_logging
    from news_bot.utils.storage import ArticleStore
else:
    from .collectors.deduplicator import Deduplicator, article_key, title_key
    from .collectors.rss_collector import Article, RSSCollector
    from .collectors.trending import TrendingScorer
    from .ai.summarizer import Summarizer
    from .image_gen.image_generator import ImageGenerator
    from .poster.facebook import FacebookPoster
    from .poster.telegram import TelegramPoster
    from .poster.wordpress import WordPressPoster
    from .scheduler import Scheduler
    from .utils.analytics import Analytics
    from .utils.config_loader import load_config
    from .utils.logger import get_logger, setup_logging
    from .utils.storage import ArticleStore


class NewsBot:
    """Top-level orchestrator. Holds state and exposes async cycle methods."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        general = cfg["general"]
        self.log = get_logger("news_bot")

        # State
        self.store = ArticleStore(general["data_dir"], cfg["collection"]["duplicate_window_hours"])
        self.store.prune()
        self.dedup = Deduplicator(self.store.all_keys())
        self.analytics = Analytics(general["data_dir"])

        # Pipeline
        self.collector = RSSCollector(
            cfg["collection"]["sources"],
            max_per_source=cfg["collection"]["max_articles_per_source"],
        )
        self.trending = TrendingScorer(cfg["viral_keywords"], cfg["categories"])
        self.summarizer = Summarizer(cfg["ai"], cfg["secrets"])
        self.image_gen = ImageGenerator(
            cfg["image"],
            output_dir=os.path.join(general["data_dir"], "images"),
            logo_path=general.get("page_logo_path"),
        )

        self.fb = FacebookPoster(
            page_id=cfg["secrets"]["facebook_page_id"],
            access_token=cfg["secrets"]["facebook_page_access_token"],
            auto_first_comment=cfg["facebook"]["auto_first_comment"],
        ) if cfg["facebook"]["enabled"] else FacebookPoster("", "")

        self.tg = TelegramPoster(
            bot_token=cfg["secrets"]["telegram_bot_token"],
            channel_id=cfg["secrets"]["telegram_channel_id"],
        ) if cfg["telegram"]["enabled"] else TelegramPoster("", "")

        self.wp = WordPressPoster(
            site_url=cfg["secrets"]["wordpress_url"],
            username=cfg["secrets"]["wordpress_username"],
            app_password=cfg["secrets"]["wordpress_app_password"],
            default_status=cfg["wordpress"]["default_status"],
        ) if cfg["wordpress"]["enabled"] else WordPressPoster("", "", "")

        # Holding queue of (article, score, category) ready for posting
        self.queue: List[Tuple[Article, float, str]] = []
        self._queue_lock = asyncio.Lock()

        self.max_per_run = cfg["scheduler"]["max_posts_per_run"]
        self.instant_breaking = cfg["scheduler"]["instant_breaking_news"]

        self._log_status()

    # ---------- core cycles ----------

    async def fetch_cycle(self) -> None:
        """Collect → dedup → score → enqueue. Posts immediately if breaking news."""
        self.log.info("=== Fetch cycle start ===")
        articles = await self.collector.collect_all()
        self.analytics.record("fetched", count=len(articles))

        unique = self.dedup.filter(articles)
        self.log.info("Unique after dedup: %d", len(unique))
        if not unique:
            return

        ranked = self.trending.rank(unique)

        async with self._queue_lock:
            for art, score, cat in ranked:
                self.queue.append((art, score, cat))
            # Keep queue bounded
            self.queue = sorted(self.queue, key=lambda x: x[1], reverse=True)[:30]

        # Instant breaking news: post anything with very high score right away
        if self.instant_breaking:
            top = ranked[0] if ranked else None
            if top and top[1] >= 5.0 and top[2] == "breaking":
                self.log.info("⚡ Instant breaking news detected: %s", top[0].title[:80])
                await self._publish_one(*top)

    async def post_cycle(self) -> None:
        """Pop top items from queue and publish to all enabled channels."""
        self.log.info("=== Post cycle start ===")
        async with self._queue_lock:
            batch = self.queue[: self.max_per_run]
            self.queue = self.queue[self.max_per_run:]

        if not batch:
            self.log.info("Nothing in queue; running an extra fetch")
            await self.fetch_cycle()
            async with self._queue_lock:
                batch = self.queue[: self.max_per_run]
                self.queue = self.queue[self.max_per_run:]

        for art, score, cat in batch:
            try:
                await self._publish_one(art, score, cat)
            except Exception as e:
                self.log.exception("Publish failed for '%s': %s", art.title[:60], e)

    async def daily_report(self) -> None:
        path = self.analytics.write_daily_report()
        if path:
            self.log.info("📊 Daily report written: %s", path)

    # ---------- helpers ----------

    async def _publish_one(self, art: Article, score: float, category: str) -> None:
        if self.store.has(article_key(art)) or self.store.has(title_key(art)):
            return

        self.log.info("Publishing [%s | %.1f]: %s", category, score, art.title[:80])

        # Summarize (sync call wrapped in executor to keep loop responsive)
        summary = await asyncio.get_event_loop().run_in_executor(
            None, self.summarizer.summarize, art, category
        )
        if not summary:
            self.log.warning("No summary produced; skipping")
            return

        # Generate image
        image_path = await asyncio.get_event_loop().run_in_executor(
            None, self.image_gen.generate, summary.headline, summary.category,
        )
        if not image_path:
            self.log.warning("No image produced; skipping")
            return

        caption = summary.caption()

        # Fan out to enabled channels
        loop = asyncio.get_event_loop()
        tasks = []
        if self.fb.is_ready():
            tasks.append(loop.run_in_executor(
                None, self.fb.post_photo, image_path, caption, art.link,
            ))
        if self.tg.is_ready():
            tasks.append(loop.run_in_executor(
                None, self.tg.post_photo, image_path, caption,
            ))
        if self.wp.is_ready():
            tasks.append(loop.run_in_executor(
                None,
                self.wp.post_article,
                summary.headline,
                f"<p>{summary.body}</p><p><a href='{art.link}'>মূল সংবাদ</a></p>",
                image_path,
                None,
            ))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.log.info("Channels published: %d", sum(1 for r in results if r and not isinstance(r, Exception)))
        else:
            self.log.warning("No posting channels enabled — keeping content local")

        # Mark as posted
        self.store.add(article_key(art))
        self.store.add(title_key(art))
        self.dedup.mark_seen(art)
        self.analytics.record(
            "posted", source=art.source, category=category, score=round(score, 2),
        )

        # Tiny inter-post delay to avoid hammering APIs
        await asyncio.sleep(2)

    def _log_status(self) -> None:
        self.log.info("─" * 60)
        self.log.info("News Bot initialized")
        self.log.info("AI provider:   %s (ready=%s)",
                      self.cfg["ai"]["provider"], self.summarizer.is_ready())
        self.log.info("Facebook:      enabled=%s ready=%s",
                      self.cfg["facebook"]["enabled"], self.fb.is_ready())
        self.log.info("Telegram:      enabled=%s ready=%s",
                      self.cfg["telegram"]["enabled"], self.tg.is_ready())
        self.log.info("WordPress:     enabled=%s ready=%s",
                      self.cfg["wordpress"]["enabled"], self.wp.is_ready())
        self.log.info("Sources:       %d enabled",
                      len([s for s in self.cfg["collection"]["sources"] if s.get("enabled", True)]))
        self.log.info("Post times:    %s (%s)",
                      self.cfg["scheduler"]["post_times"], self.cfg["general"]["timezone"])
        self.log.info("─" * 60)


async def amain() -> None:
    # Resolve config relative to this file so it works from anywhere
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, "config.json")
    cfg = load_config(cfg_path)

    setup_logging(
        logs_dir=os.path.join(here, cfg["general"]["logs_dir"]),
        level=cfg["logging"]["level"],
        max_bytes=cfg["logging"]["max_bytes"],
        backup_count=cfg["logging"]["backup_count"],
    )

    # Resolve data dir relative to module
    cfg["general"]["data_dir"] = os.path.join(here, cfg["general"]["data_dir"])
    cfg["general"]["logs_dir"] = os.path.join(here, cfg["general"]["logs_dir"])
    if cfg["general"].get("page_logo_path"):
        cfg["general"]["page_logo_path"] = os.path.join(here, cfg["general"]["page_logo_path"])

    bot = NewsBot(cfg)
    scheduler = Scheduler(
        timezone=cfg["general"]["timezone"],
        post_times=cfg["scheduler"]["post_times"],
        fetch_interval_minutes=cfg["collection"]["fetch_interval_minutes"],
        fetch_callback=bot.fetch_cycle,
        post_callback=bot.post_cycle,
        daily_callback=bot.daily_report,
    )

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, scheduler.stop)
        except NotImplementedError:
            # Windows fallback
            pass

    await scheduler.run()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
