"""Time-based scheduling for fetch + post (image bot) + video bot + cache cleanup."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Awaitable, Callable, List, Optional

import pytz

from utils.logger import get_logger

log = get_logger(__name__)


class Scheduler:
    """Lightweight async scheduler.

    Drives four independent cadences:
      - fetch_callback                — every ``fetch_interval_minutes``
      - post_callback                 — fixed times OR ``post_interval_minutes`` cadence
      - video_post_callback (opt)     — every ``video_post_interval_minutes``
      - cache_clean_callback (opt)    — every ``cache_clean_interval_minutes``
      - daily_callback                — once per day at 23:55 local
    """

    def __init__(self,
                 timezone: str,
                 post_times: List[str],
                 fetch_interval_minutes: int,
                 fetch_callback: Callable[[], Awaitable[None]],
                 post_callback: Callable[[], Awaitable[None]],
                 daily_callback: Callable[[], Awaitable[None]],
                 post_interval_minutes: int = 0,
                 active_hours: tuple = (6, 23),
                 video_fetch_callback: Optional[Callable[[], Awaitable[None]]] = None,
                 video_post_callback: Optional[Callable[[], Awaitable[None]]] = None,
                 video_post_interval_minutes: int = 0,
                 cache_clean_callback: Optional[Callable[[], Awaitable[None]]] = None,
                 cache_clean_interval_minutes: int = 60):
        self.tz = pytz.timezone(timezone)
        self.post_times = post_times
        self.fetch_interval = max(1, fetch_interval_minutes) * 60
        self.post_interval = max(0, post_interval_minutes) * 60
        self.video_post_interval = max(0, video_post_interval_minutes) * 60
        self.cache_clean_interval = max(1, cache_clean_interval_minutes) * 60
        self.active_start, self.active_end = active_hours

        self.fetch_cb = fetch_callback
        self.post_cb = post_callback
        self.daily_cb = daily_callback
        self.video_fetch_cb = video_fetch_callback
        self.video_post_cb = video_post_callback
        self.cache_clean_cb = cache_clean_callback

        self._stop = asyncio.Event()
        self._fired_today: set = set()
        self._daily_fired_date: str = ""

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        log.info(
            "Scheduler started (tz=%s, post_times=%s, fetch_every=%ds, "
            "video_every=%ds, cache_clean_every=%ds)",
            self.tz, self.post_times, self.fetch_interval,
            self.video_post_interval, self.cache_clean_interval,
        )

        # Boot cycle: do useful work immediately
        try:
            await self.fetch_cb()
            await self.post_cb()
            if self.video_fetch_cb:
                await self.video_fetch_cb()
        except Exception as e:
            log.exception("Initial cycle failed: %s", e)

        last_fetch = datetime.utcnow()
        last_post = datetime.utcnow()
        last_video = datetime.utcnow()
        last_cache = datetime.utcnow()

        while not self._stop.is_set():
            now_local = datetime.now(self.tz)
            today_str = now_local.strftime("%Y-%m-%d")

            if self._daily_fired_date != today_str:
                self._fired_today.clear()
                self._daily_fired_date = today_str

            current_hm = now_local.strftime("%H:%M")
            in_active_window = self.active_start <= now_local.hour <= self.active_end

            # ── Image post trigger ─────────────────────────────────
            if self.post_interval > 0:
                if (in_active_window and
                        (datetime.utcnow() - last_post).total_seconds() >= self.post_interval):
                    last_post = datetime.utcnow()
                    log.info("Image post window hit (%s)", current_hm)
                    try:
                        await self.post_cb()
                    except Exception as e:
                        log.exception("Image post failed: %s", e)
            else:
                for t in self.post_times:
                    key = f"{today_str}-{t}"
                    if current_hm == t and key not in self._fired_today:
                        log.info("Scheduled post window hit: %s", t)
                        self._fired_today.add(key)
                        try:
                            await self.post_cb()
                        except Exception as e:
                            log.exception("Scheduled post failed: %s", e)

            # ── Video post trigger ─────────────────────────────────
            if (self.video_post_cb and self.video_post_interval > 0 and
                    in_active_window and
                    (datetime.utcnow() - last_video).total_seconds() >= self.video_post_interval):
                last_video = datetime.utcnow()
                log.info("🎬 Video post window hit (%s)", current_hm)
                try:
                    await self.video_post_cb()
                except Exception as e:
                    log.exception("Video post failed: %s", e)

            # ── Cache cleaner trigger ──────────────────────────────
            if (self.cache_clean_cb and
                    (datetime.utcnow() - last_cache).total_seconds() >= self.cache_clean_interval):
                last_cache = datetime.utcnow()
                try:
                    await self.cache_clean_cb()
                except Exception as e:
                    log.exception("Cache clean failed: %s", e)

            # ── Daily analytics at 23:55 local ─────────────────────
            daily_key = f"{today_str}-daily"
            if current_hm == "23:55" and daily_key not in self._fired_today:
                self._fired_today.add(daily_key)
                try:
                    await self.daily_cb()
                except Exception as e:
                    log.exception("Daily report failed: %s", e)

            # ── Periodic fetches ───────────────────────────────────
            if (datetime.utcnow() - last_fetch).total_seconds() >= self.fetch_interval:
                last_fetch = datetime.utcnow()
                try:
                    await self.fetch_cb()
                    if self.video_fetch_cb:
                        await self.video_fetch_cb()
                except Exception as e:
                    log.exception("Fetch cycle failed: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass

        log.info("Scheduler stopped")
