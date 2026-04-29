"""Main entrypoint: wires collectors → AI → image gen → Facebook (image + video bot) + scheduler + cache cleaner."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from collectors.deduplicator import Deduplicator, article_key, title_key
from collectors.rss_collector import Article, RSSCollector
from collectors.trending import TrendingScorer
from ai.summarizer import Summarizer
from image_gen.image_generator import ImageGenerator
from poster.facebook import FacebookPoster
from scheduler import Scheduler
from utils.analytics import Analytics
from utils.cache_cleaner import CacheCleaner
from utils.config_loader import load_config
from utils.logger import get_logger, setup_logging
from utils.storage import ArticleStore
from video.news_video_maker import NewsVideoMaker
from video.video_orchestrator import VideoBot
from video.video_poster import VideoPoster


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

        # Pipeline (image / text bot)
        self.collector = RSSCollector(
            cfg["collection"]["sources"],
            max_per_source=cfg["collection"]["max_articles_per_source"],
            max_age_hours=int(cfg["collection"].get("max_article_age_hours", 24)),
        )
        self.trending = TrendingScorer(cfg["viral_keywords"], cfg["categories"])
        self.summarizer = Summarizer(cfg["ai"], cfg["secrets"])
        self.image_gen = ImageGenerator(
            cfg["image"],
            output_dir=os.path.join(general["data_dir"], "images"),
            logo_path=general.get("page_logo_path"),
        )

        # Facebook posters: photo path is kept as fallback, video path is
        # the new default for every news article.
        page_id = cfg["secrets"]["facebook_page_id"] if cfg["facebook"]["enabled"] else ""
        token = cfg["secrets"]["facebook_page_access_token"] if cfg["facebook"]["enabled"] else ""

        self.fb = FacebookPoster(
            page_id=page_id, access_token=token,
            auto_first_comment=cfg["facebook"]["auto_first_comment"],
        )
        self.fb_video = VideoPoster(page_id=page_id, access_token=token)

        # NEW: news video maker (image + random BG audio → 15-20s mp4)
        nvm_cfg = cfg.get("news_video", {})
        audio_dir = os.path.join(
            os.path.dirname(general["data_dir"]),
            nvm_cfg.get("audio_dir", "audio"),
        )
        self.news_video_enabled = bool(nvm_cfg.get("enabled", True))
        self.delete_video_after_post = bool(nvm_cfg.get("delete_video_after_post", True))
        self.news_video_maker = NewsVideoMaker(
            nvm_cfg,
            output_dir=os.path.join(general["data_dir"], "videos"),
            audio_dir=audio_dir,
        )

        # Video bot (independent pipeline — YouTube/Wikimedia/etc. clips)
        self.video_bot = VideoBot(
            cfg.get("video_bot", {}), cfg["secrets"],
            data_dir=general["data_dir"],
            fb_credit=cfg["image"].get("bot_credit", "BOT BY TOHIDUL"),
            brand_name=cfg["image"].get("brand_name", "News Summary"),
            font_path=self.image_gen.font_path,
        )

        # Cache cleaner
        self.cache = CacheCleaner(
            cfg.get("cache", {}),
            paths={
                "images_dir":  os.path.join(general["data_dir"], "images"),
                "videos_dir":  os.path.join(general["data_dir"], "videos"),
                "data_dir":    general["data_dir"],
                "events_path": os.path.join(general["data_dir"], "events.jsonl"),
                "logs_dir":    general["logs_dir"],
            },
        )

        # Holding queue of (article, score, category) ready for posting
        self.queue: List[Tuple[Article, float, str]] = []
        self._queue_lock = asyncio.Lock()

        sched = cfg["scheduler"]
        self.max_per_run = sched["max_posts_per_run"]
        self.instant_breaking = sched["instant_breaking_news"]

        # Real-time mode: every fresh article in a fetch cycle is published
        # immediately (throttled by `min_seconds_between_posts`).
        self.realtime_mode: bool = bool(sched.get("realtime_mode", False))
        self.min_seconds_between_posts: int = int(sched.get("min_seconds_between_posts", 25))
        self.max_posts_per_fetch: int = int(sched.get("max_posts_per_fetch", 8))
        self.delete_image_after_post: bool = bool(sched.get("delete_image_after_post", True))
        self._last_post_ts: float = 0.0

        self._log_status()

    # ---------- core cycles ----------

    async def fetch_cycle(self) -> None:
        """Collect → dedup → score → enqueue (or publish immediately in realtime mode)."""
        self.log.info("=== Fetch cycle start ===")
        articles = await self.collector.collect_all()
        self.analytics.record("fetched", count=len(articles))

        unique = self.dedup.filter(articles)
        self.log.info("Unique after dedup: %d", len(unique))
        if not unique:
            return

        ranked = self.trending.rank(unique)

        # ── Real-time mode: publish each new article straight to FB,
        # throttled, capped at max_posts_per_fetch ──
        if self.realtime_mode:
            self.log.info("⚡ Realtime mode: publishing up to %d new article(s) immediately",
                          self.max_posts_per_fetch)
            published = 0
            for art, score, cat in ranked:
                if published >= self.max_posts_per_fetch:
                    self.log.info("Reached max_posts_per_fetch=%d for this cycle",
                                  self.max_posts_per_fetch)
                    break
                # Throttle between consecutive posts
                wait = self.min_seconds_between_posts - (time.time() - self._last_post_ts)
                if wait > 0 and self._last_post_ts > 0:
                    self.log.info("⏳ Throttling: waiting %.1fs before next post", wait)
                    await asyncio.sleep(wait)
                try:
                    posted = await self._publish_one(art, score, cat)
                    if posted:
                        published += 1
                        self._last_post_ts = time.time()
                except Exception as e:
                    self.log.exception("Realtime publish failed for '%s': %s",
                                       art.title[:60], e)
            self.log.info("⚡ Realtime cycle done: %d new article(s) published", published)
            return

        # ── Classic mode: enqueue + post on a separate cycle ──
        async with self._queue_lock:
            for art, score, cat in ranked:
                self.queue.append((art, score, cat))
            self.queue = sorted(self.queue, key=lambda x: x[1], reverse=True)[:30]

        if self.instant_breaking:
            top = ranked[0] if ranked else None
            if top and top[1] >= 5.0 and top[2] == "breaking":
                self.log.info("⚡ Instant breaking news detected: %s", top[0].title[:80])
                await self._publish_one(*top)

    async def post_cycle(self) -> None:
        """Pop top items from queue and publish to Facebook."""
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

    async def cache_clean_cycle(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.cache.run)

    # ---------- helpers ----------

    async def _publish_one(self, art: Article, score: float, category: str) -> bool:
        """Pipeline: summarize → image → 15-20s video → Facebook video post.

        Returns True if the article was successfully published.
        """
        if self.store.has(article_key(art)) or self.store.has(title_key(art)):
            return False

        self.log.info("Publishing [%s | %.1f]: %s", category, score, art.title[:80])

        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            None, self.summarizer.summarize, art, category,
        )
        if not summary:
            self.log.warning("No summary produced; skipping")
            return False

        self.log.info("📝 Headline: %s", summary.headline)
        self.log.info("📝 Body: %s", summary.body[:160])

        # 1. Generate the clean news-card image (headline + body only)
        image_path = await loop.run_in_executor(
            None, self.image_gen.generate,
            summary.headline, summary.body, summary.category,
        )
        if not image_path:
            self.log.warning("No image produced; skipping")
            return False

        caption = summary.caption()
        success = False
        video_path: Optional[str] = None

        # 2. Build the news video (image + random BG audio → 15-20 s mp4)
        if self.news_video_enabled and self.news_video_maker.is_ready():
            video_path = await loop.run_in_executor(
                None, self.news_video_maker.make, image_path, summary.category,
            )
        else:
            self.log.info("News video disabled — falling back to photo post")

        # 3. Publish: prefer video; if it failed, gracefully fall back to photo
        if video_path and self.fb_video.is_ready():
            post_id = await loop.run_in_executor(
                None,
                self._post_news_video, video_path, summary.headline, caption,
            )
            if post_id:
                success = True
            else:
                self.log.warning("Video upload failed — falling back to photo post")

        if not success and self.fb.is_ready():
            post_id = await loop.run_in_executor(
                None, self.fb.post_photo, image_path, caption, art.link,
            )
            if post_id:
                success = True
            else:
                self.log.warning("Facebook publish failed for: %s",
                                 summary.headline[:60])

        if not success and not self.fb.is_ready():
            self.log.warning("Facebook not configured — content kept local only")
            success = True  # treat as ok so we still mark seen + cleanup

        if not success:
            self._safe_remove(video_path)
            return False

        # 4. Mark seen + record analytics
        self.store.add(article_key(art))
        self.store.add(title_key(art))
        self.dedup.mark_seen(art)
        self.analytics.record(
            "posted", source=art.source, category=category, score=round(score, 2),
            kind=("video" if video_path else "image"),
        )

        # 5. Cleanup local artefacts to free disk space
        if self.delete_image_after_post:
            self._safe_remove(image_path, label="Image")
        if self.delete_video_after_post:
            self._safe_remove(video_path, label="Video")

        await asyncio.sleep(2)
        return True

    def _post_news_video(self, video_path: str, headline: str,
                         caption: str) -> Optional[str]:
        """Wrap the video poster so it accepts (path, headline, caption)."""
        # The VideoPoster expects a VideoItem — build a minimal one in-place.
        from video.video_collector import VideoItem
        item = VideoItem(
            title=headline, description="", video_url="", page_url="",
            source="News Bot", license_name="", author="",
            published=None, duration_seconds=0, thumbnail_url="",
        )
        return self.fb_video.post_video(video_path, item, caption)

    def _safe_remove(self, path: Optional[str], label: str = "File") -> None:
        if not path:
            return
        try:
            if os.path.isfile(path):
                os.remove(path)
                self.log.info("🧹 %s removed: %s", label, os.path.basename(path))
        except Exception as e:
            self.log.warning("Could not delete %s %s: %s", label.lower(), path, e)

    def _log_status(self) -> None:
        self.log.info("─" * 60)
        self.log.info("News Bot initialized (Image + Video pipelines)")
        self.log.info("AI provider:   %s (ready=%s)",
                      self.cfg["ai"]["provider"], self.summarizer.is_ready())
        self.log.info("Facebook:      enabled=%s ready=%s",
                      self.cfg["facebook"]["enabled"], self.fb.is_ready())
        self.log.info("Video bot:     enabled=%s ready=%s",
                      self.video_bot.enabled, self.video_bot.poster.is_ready())
        self.log.info("Sources:       %d enabled (realtime monitoring every %d min)",
                      len([s for s in self.cfg["collection"]["sources"] if s.get("enabled", True)]),
                      self.cfg["collection"]["fetch_interval_minutes"])
        self.log.info("Realtime mode: %s (max %d posts/cycle, %ds throttle)",
                      self.realtime_mode, self.max_posts_per_fetch,
                      self.min_seconds_between_posts)
        self.log.info("Auto-cleanup:  delete_image_after_post=%s",
                      self.delete_image_after_post)
        self.log.info("Post times:    %s (%s)",
                      self.cfg["scheduler"]["post_times"], self.cfg["general"]["timezone"])
        self.log.info("─" * 60)


async def amain() -> None:
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

    bot = NewsBot(cfg)
    scheduler = Scheduler(
        timezone=cfg["general"]["timezone"],
        post_times=cfg["scheduler"].get("post_times", []),
        fetch_interval_minutes=cfg["collection"]["fetch_interval_minutes"],
        fetch_callback=bot.fetch_cycle,
        post_callback=bot.post_cycle,
        daily_callback=bot.daily_report,
        post_interval_minutes=cfg["scheduler"].get("post_interval_minutes", 0),
        active_hours=tuple(cfg["scheduler"].get("active_hours", [6, 23])),
        video_fetch_callback=bot.video_bot.fetch_cycle if bot.video_bot.enabled else None,
        video_post_callback=bot.video_bot.post_cycle if bot.video_bot.enabled else None,
        video_post_interval_minutes=cfg["scheduler"].get("video_post_interval_minutes", 0),
        cache_clean_callback=bot.cache_clean_cycle,
        cache_clean_interval_minutes=cfg["scheduler"].get("cache_clean_interval_minutes", 60),
    )

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, scheduler.stop)
        except NotImplementedError:
            pass

    await scheduler.run()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
