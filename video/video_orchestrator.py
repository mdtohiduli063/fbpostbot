"""Top-level video bot orchestrator: collect → translate headline → process → post."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ai.summarizer import CATEGORY_EMOJI
from ai.translator import Translator
from utils.logger import get_logger
from utils.storage import ArticleStore
from .video_collector import VideoCollector, VideoItem
from .video_poster import VideoPoster
from .video_processor import VideoProcessor

log = get_logger(__name__)


def _video_key(item: VideoItem) -> str:
    """Stable de-dup key for a video item."""
    return item.video_url.strip() or item.page_url.strip() or item.title.strip()


class VideoBot:
    """Orchestrator for the copyright-free video posting pipeline."""

    def __init__(self, cfg: Dict[str, Any], secrets: Dict[str, str],
                 data_dir: str, fb_credit: str = "BOT BY TOHIDUL",
                 brand_name: str = "News Summary",
                 font_path: Optional[str] = None):
        self.cfg = cfg
        self.secrets = secrets
        self.enabled = bool(cfg.get("enabled", False))
        self.max_per_run = int(cfg.get("max_posts_per_run", 1))
        self.translate_to_bn = bool(cfg.get("translate_to_bangla", True))

        self.collector = VideoCollector(cfg, secrets)
        self.processor = VideoProcessor(
            cfg.get("processor", {}),
            output_dir=f"{data_dir}/videos",
            brand_name=brand_name, bot_credit=fb_credit, font_path=font_path,
        )
        self.poster = VideoPoster(
            page_id=secrets.get("facebook_page_id", ""),
            access_token=secrets.get("facebook_page_access_token", ""),
        )
        self.translator = Translator("bn") if self.translate_to_bn else None
        self.store = ArticleStore(
            f"{data_dir}/videos",
            ttl_hours=int(cfg.get("dedup_ttl_hours", 168)),
        )
        self.store.prune()
        self.queue: List[VideoItem] = []
        self._lock = asyncio.Lock()

    # ───────────────────────────── public cycles ─────────────────────────────

    async def fetch_cycle(self) -> None:
        if not self.enabled:
            return
        log.info("=== Video fetch cycle start ===")
        items = await self.collector.collect_all()
        # Skip already-posted videos
        unique = [it for it in items if not self.store.has(_video_key(it))]
        log.info("🎬 Video unique after dedup: %d", len(unique))
        async with self._lock:
            self.queue = (self.queue + unique)[:30]

    async def post_cycle(self) -> None:
        if not self.enabled:
            return
        log.info("=== Video post cycle start ===")
        async with self._lock:
            batch = self.queue[: self.max_per_run]
            self.queue = self.queue[self.max_per_run:]

        if not batch:
            log.info("Video queue empty — running an extra fetch")
            await self.fetch_cycle()
            async with self._lock:
                batch = self.queue[: self.max_per_run]
                self.queue = self.queue[self.max_per_run:]

        for item in batch:
            try:
                await self._publish_one(item)
            except Exception as e:
                log.exception("Video publish failed: %s", e)

    # ─────────────────────────── helpers ───────────────────────────

    async def _publish_one(self, item: VideoItem) -> None:
        key = _video_key(item)
        if self.store.has(key):
            return
        # Translate headline for top ribbon
        headline_bn = item.title
        if self.translator and self._is_mostly_english(item.title):
            translated = self.translator.translate(item.title)
            if translated:
                headline_bn = translated
        log.info("🎬 Processing video: %s", headline_bn[:80])

        # processor.process is async; the heavy ffmpeg call inside runs via
        # subprocess.run which blocks — but it's a short-lived blocking call
        # we accept here since the bot has only one orchestrator running.
        out_path = await self.processor.process(item, headline_bn)
        if not out_path:
            log.warning("Video processing produced no output, skipping")
            return

        loop = asyncio.get_event_loop()
        caption = self._build_caption(item, headline_bn)
        post_id = await loop.run_in_executor(
            None, self.poster.post_video, out_path, item, caption,
        )
        if not post_id:
            log.warning("Video upload failed for: %s", item.title[:60])
            return

        self.store.add(key)
        log.info("✅ Video bot published: %s", post_id)
        await asyncio.sleep(2)

    def _build_caption(self, item: VideoItem, headline_bn: str) -> str:
        emoji = "🎥"
        sep = "━━━━━━━━━━━━━━━━━━━━━"
        body = (item.description or "").strip()[:600]
        lines = [
            f"{emoji} {headline_bn.strip()}",
            sep,
        ]
        if body:
            lines += [body, ""]
        lines += [
            f"📡 সূত্র: {item.source}",
        ]
        if item.author:
            lines.append(f"✍️ স্রষ্টা: {item.author}")
        if item.license_name:
            lines.append(f"⚖️ লাইসেন্স: {item.license_name}")
        if item.page_url:
            lines.append(f"🔗 মূল: {item.page_url}")
        lines += [
            "",
            "🤖 BOT BY TOHIDUL",
            "",
            "#VideoNews #BanglaNews #CopyrightFree #PublicDomain "
            "#বাংলাদেশ #সংবাদ #ভিডিও_সংবাদ",
        ]
        return "\n".join(lines)

    @staticmethod
    def _is_mostly_english(text: str) -> bool:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False
        ascii_letters = [c for c in letters if c.isascii()]
        return (len(ascii_letters) / len(letters)) > 0.6
