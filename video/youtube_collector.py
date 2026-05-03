"""YouTube channel collector — pulls latest uploads from configured news
channels (e.g. Jamuna TV, Somoy TV) and picks the *most-replayed* segment
to repost to Facebook.

⚠️  IMPORTANT — COPYRIGHT NOTICE  ⚠️
This collector pulls content from copyrighted commercial news channels.
That is **not** copyright-free. Posting these clips to Facebook can:
  • Trigger automatic Rights Manager takedowns
  • Earn page strikes (3 strikes → page disabled)
  • Block monetisation

Mitigations baked in here:
  • Clips are **strictly capped** to a short segment (default 15 s)
  • Original channel is credited prominently in caption
  • License field is set to "Editorial / Fair-Use" so the caption is honest
Use at your own risk. Prefer the public-domain / CC sources whenever
possible.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from .video_collector import VideoItem

log = get_logger(__name__)


class YouTubeCollector:
    """Lists recent uploads from configured YouTube channels and picks the
    most-replayed segment of each video as the clip to repost."""

    def __init__(self, cfg: Dict[str, Any]):
        self.enabled = bool(cfg.get("enabled", False))
        self.channels: List[Dict[str, str]] = cfg.get("channels", [])
        self.max_per_channel = int(cfg.get("max_per_channel", 3))
        self.search_queries: List[str] = cfg.get("search_queries", [])
        # Per-clip duration is randomised between segment_seconds_min..max,
        # so each repost feels different (15-20 s by default).
        self.segment_seconds_min = int(cfg.get("segment_seconds_min",
                                               cfg.get("segment_seconds", 15)))
        self.segment_seconds_max = int(cfg.get("segment_seconds_max",
                                               cfg.get("segment_seconds", 20)))
        if self.segment_seconds_max < self.segment_seconds_min:
            self.segment_seconds_max = self.segment_seconds_min
        # Hard upper bound for safety (longer = higher copyright risk)
        self.max_segment_seconds = int(cfg.get("max_segment_seconds", 60))
        # Skip a few seconds of channel intro / sting when no heatmap exists
        self.intro_skip_seconds = int(cfg.get("intro_skip_seconds", 5))
        # Don't bother with very short / very long uploads
        self.min_video_duration = int(cfg.get("min_video_duration_seconds", 30))
        self.max_video_duration = int(cfg.get("max_video_duration_seconds", 1800))

    # ─────────────────────────── public API ───────────────────────────

    async def collect(self) -> List[VideoItem]:
        if not self.enabled or not self.channels:
            return []
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            log.error("yt-dlp not installed — YouTube collector disabled")
            return []

        items: List[VideoItem] = []
        for ch in self.channels:
            try:
                got = await asyncio.to_thread(self._collect_channel, ch)
                items.extend(got)
                log.info("📺 YouTube [%s]: %d clip(s)", ch.get("name", "?"), len(got))
            except Exception as e:
                log.warning("YouTube channel failed (%s): %s",
                            ch.get("name", ch.get("url", "?")), e)
        return items

    # ─────────────────────────── internals ───────────────────────────

    def _collect_channel(self, ch: Dict[str, str]) -> List[VideoItem]:
        import yt_dlp

        channel_url = ch.get("url", "").strip()
        if not channel_url:
            return []

        list_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": self.max_per_channel,
            "nocheckcertificate": True,
            "retries": 3,
            "extractor_retries": 3,
            "extractor_args": {
                "youtube": {
                    "skip": ["webpage", "dash", "hls"],
                }
            },
        }
        entries: List[Dict[str, Any]] = []
        urls = [channel_url]
        if "/videos" not in channel_url:
            urls.append(channel_url.rstrip("/") + "/videos")
        for url in urls:
            try:
                with yt_dlp.YoutubeDL(list_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                entries = (info.get("entries") or [])[: self.max_per_channel]
                if entries:
                    break
            except Exception as e:
                log.warning("YouTube list fetch failed for %s: %s", ch.get("name", url), e)
                continue
        if not entries and self.search_queries:
            query = random.choice(self.search_queries)
            try:
                with yt_dlp.YoutubeDL(list_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch{self.max_per_channel}:{query}", download=False)
                entries = (info.get("entries") or [])[: self.max_per_channel]
            except Exception as e:
                log.warning("YouTube search fallback failed for %s: %s", query, e)
                entries = []

        results: List[VideoItem] = []
        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            try:
                full = self._fetch_full(vid)
            except Exception as exc:
                log.warning("YT meta fetch failed for %s: %s", vid, exc)
                continue
            if not full:
                continue

            duration = int(full.get("duration") or 0)
            if duration and (duration < self.min_video_duration
                             or duration > self.max_video_duration):
                continue

            start, dur = self._pick_segment(full, duration)
            ts = full.get("timestamp")
            published = (datetime.fromtimestamp(ts, tz=timezone.utc)
                         if ts else None)

            results.append(VideoItem(
                title=full.get("title") or "",
                description=(full.get("description") or "")[:600],
                # video_url stays as the YT page URL; processor handles it
                video_url=f"https://www.youtube.com/watch?v={vid}",
                page_url=f"https://www.youtube.com/watch?v={vid}",
                source=ch.get("name") or full.get("uploader") or "YouTube",
                license_name=ch.get(
                    "license_label",
                    "© Original Channel — Editorial / Fair Use",
                ),
                author=full.get("uploader") or ch.get("name", ""),
                published=published,
                # Report the *segment* duration so the orchestrator's
                # duration window filter doesn't drop long source videos.
                duration_seconds=int(dur or 0),
                thumbnail_url=full.get("thumbnail") or "",
                extras={
                    "youtube_id": vid,
                    "trim_start": float(start),
                    "trim_duration": float(dur),
                    "source_duration_seconds": duration,
                    "channel_name": ch.get("name", ""),
                    "had_heatmap": bool(full.get("heatmap")),
                },
            ))
        return results

    # ─── metadata + heatmap ───
    def _fetch_full(self, video_id: str) -> Optional[Dict[str, Any]]:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "youtube_include_dash_manifest": False,
            "nocheckcertificate": True,
            "retries": 3,
            "extractor_retries": 3,
            "extractor_args": {
                "youtube": {
                    "skip": ["webpage", "dash", "hls"],
                }
            },
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )

    # ─── most-replayed window picker ───
    def _pick_segment(self, info: Dict[str, Any],
                      duration: int) -> tuple[float, float]:
        """Returns (start_seconds, segment_seconds).

        Each call randomises the segment length within
        [segment_seconds_min, segment_seconds_max] so reposts feel fresh.
        """
        import random as _random
        target = float(_random.randint(
            self.segment_seconds_min, self.segment_seconds_max,
        ))
        target = min(target, float(self.max_segment_seconds))
        if duration <= 0:
            return 0.0, target

        # Cap target to actual video length (minus a tiny buffer)
        target = min(target, max(1.0, duration - 1.0))

        heatmap = info.get("heatmap") or []
        if not heatmap:
            # No heatmap → skip a small intro and grab the lead
            start = float(min(self.intro_skip_seconds,
                              max(0, duration - target)))
            return start, target

        # Sample the heatmap value at every second in [0, duration)
        samples = [0.0] * max(1, int(duration))
        for h in heatmap:
            try:
                s = max(0, int(h.get("start_time", 0)))
                e = min(int(duration), int(h.get("end_time", s + 1)))
                v = float(h.get("value", 0.0))
            except (TypeError, ValueError):
                continue
            for i in range(s, e):
                if i < len(samples):
                    samples[i] = v

        win = int(target)
        if win <= 0 or win >= len(samples):
            return 0.0, target

        # Sliding-window sum to find the densest window
        running = sum(samples[:win])
        best_score, best_start = running, 0
        for i in range(1, len(samples) - win + 1):
            running += samples[i + win - 1] - samples[i - 1]
            if running > best_score:
                best_score, best_start = running, i

        return float(best_start), target
