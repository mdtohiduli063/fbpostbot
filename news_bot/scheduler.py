"""Time-based scheduling for routine fetch + scheduled posting windows."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Awaitable, Callable, List

import pytz

from .utils.logger import get_logger

log = get_logger(__name__)


class Scheduler:
    """Lightweight async scheduler.

    - Runs ``fetch_callback`` every ``fetch_interval_minutes``.
    - Triggers ``post_callback`` once at each configured local time per day.
    - Runs ``daily_callback`` once per day at 23:55 local for analytics.
    """

    def __init__(self,
                 timezone: str,
                 post_times: List[str],
                 fetch_interval_minutes: int,
                 fetch_callback: Callable[[], Awaitable[None]],
                 post_callback: Callable[[], Awaitable[None]],
                 daily_callback: Callable[[], Awaitable[None]],
                 post_interval_minutes: int = 0,
                 active_hours: tuple = (6, 23)):
        """If ``post_interval_minutes`` > 0, post on a fixed cadence (e.g. every
        60 min) within ``active_hours`` and ignore ``post_times``."""
        self.tz = pytz.timezone(timezone)
        self.post_times = post_times
        self.fetch_interval = max(1, fetch_interval_minutes) * 60
        self.post_interval = max(0, post_interval_minutes) * 60
        self.active_start, self.active_end = active_hours
        self.fetch_cb = fetch_callback
        self.post_cb = post_callback
        self.daily_cb = daily_callback
        self._stop = asyncio.Event()
        self._fired_today: set = set()
        self._daily_fired_date: str = ""

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        log.info(
            "Scheduler started (tz=%s, post_times=%s, fetch_every=%ds)",
            self.tz, self.post_times, self.fetch_interval,
        )

        # Kick off an initial fetch + post cycle so the bot does useful work on boot
        try:
            await self.fetch_cb()
            await self.post_cb()
        except Exception as e:
            log.exception("Initial cycle failed: %s", e)

        last_fetch = datetime.utcnow()
        last_post = datetime.utcnow()

        while not self._stop.is_set():
            now_local = datetime.now(self.tz)
            today_str = now_local.strftime("%Y-%m-%d")

            # Reset fired-times set at midnight
            if self._daily_fired_date != today_str:
                self._fired_today.clear()
                self._daily_fired_date = today_str

            # ── Posting trigger ──────────────────────────────────────
            current_hm = now_local.strftime("%H:%M")
            in_active_window = self.active_start <= now_local.hour <= self.active_end

            if self.post_interval > 0:
                # Interval mode (e.g. every 60 minutes)
                if (in_active_window and
                        (datetime.utcnow() - last_post).total_seconds() >= self.post_interval):
                    last_post = datetime.utcnow()
                    log.info("Hourly post window hit (%s)", current_hm)
                    try:
                        await self.post_cb()
                    except Exception as e:
                        log.exception("Hourly post failed: %s", e)
            else:
                # Fixed-times mode
                for t in self.post_times:
                    key = f"{today_str}-{t}"
                    if current_hm == t and key not in self._fired_today:
                        log.info("Scheduled post window hit: %s", t)
                        self._fired_today.add(key)
                        try:
                            await self.post_cb()
                        except Exception as e:
                            log.exception("Scheduled post failed: %s", e)

            # Daily analytics at 23:55 local
            daily_key = f"{today_str}-daily"
            if current_hm == "23:55" and daily_key not in self._fired_today:
                self._fired_today.add(daily_key)
                try:
                    await self.daily_cb()
                except Exception as e:
                    log.exception("Daily report failed: %s", e)

            # Periodic fetch (which also handles instant breaking-news posting)
            if (datetime.utcnow() - last_fetch).total_seconds() >= self.fetch_interval:
                last_fetch = datetime.utcnow()
                try:
                    await self.fetch_cb()
                except Exception as e:
                    log.exception("Fetch cycle failed: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass

        log.info("Scheduler stopped")
