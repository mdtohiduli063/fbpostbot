"""Download a copyright-free video clip and overlay credit + brand watermark.

Uses ffmpeg via subprocess. Produces a 1080×1080 (or original-aspect, 30fps)
MP4 ready for Facebook upload, with three baked-in overlays:

  1. Top ribbon  — single-line bold Bangla headline
  2. Bottom bar  — credit line ("সূত্র: VOA News · Public Domain")
  3. Side stamp  — "BOT BY TOHIDUL" brand mark

Output filename includes the timestamp + category for easy cleanup.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

from ..utils.logger import get_logger
from .video_collector import VideoItem

log = get_logger(__name__)


def _safe_filename(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", s)
    return s.strip("_")[:60] or "video"


class VideoProcessor:
    """Download + watermark + transcode video clips."""

    def __init__(self, cfg: Dict[str, Any], output_dir: str,
                 brand_name: str = "News Summary",
                 bot_credit: str = "BOT BY TOHIDUL",
                 font_path: Optional[str] = None):
        self.cfg = cfg
        self.output_dir = output_dir
        self.brand_name = brand_name
        self.bot_credit = bot_credit
        self.font_path = font_path
        self.max_duration = int(cfg.get("max_output_seconds", 90))
        self.target_fps   = int(cfg.get("target_fps", 30))
        self.target_width = int(cfg.get("target_width", 1080))
        self.target_height = int(cfg.get("target_height", 1080))
        self.bitrate = cfg.get("video_bitrate", "1800k")
        self.audio_bitrate = cfg.get("audio_bitrate", "128k")
        self.download_timeout = int(cfg.get("download_timeout_seconds", 90))
        os.makedirs(output_dir, exist_ok=True)
        self._raw_dir = os.path.join(output_dir, "_raw")
        os.makedirs(self._raw_dir, exist_ok=True)

        if not shutil.which("ffmpeg"):
            log.warning("ffmpeg not found in PATH — video processing will fail")

    # ────────────────────────── public ──────────────────────────

    async def process(self, item: VideoItem, headline: str,
                      category: str = "general") -> Optional[str]:
        """Download `item` and produce a watermarked, FB-ready MP4.

        Returns the final output path or None on failure."""
        raw_path = await self._download(item)
        if not raw_path:
            return None
        try:
            out = self._ffmpeg_render(raw_path, item, headline, category)
            return out
        finally:
            # Always remove the raw download to save disk space
            try:
                os.remove(raw_path)
            except OSError:
                pass

    # ────────────────────────── download ──────────────────────────

    async def _download(self, item: VideoItem) -> Optional[str]:
        if not item.video_url:
            return None
        ext = os.path.splitext(item.video_url.split("?")[0])[1].lower()
        if ext not in (".mp4", ".webm", ".mov", ".mkv", ".m4v", ".ogv"):
            ext = ".mp4"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = f"raw_{_safe_filename(item.source)}_{ts}{ext}"
        path = os.path.join(self._raw_dir, fname)

        timeout = aiohttp.ClientTimeout(total=self.download_timeout)
        # Wikimedia + Internet Archive reject blank or "bot" UAs with 403,
        # so we send a browser-style UA.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(item.video_url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        log.warning("Video download HTTP %d for %s",
                                    resp.status, item.video_url[:80])
                        return None
                    with open(path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1 << 16):
                            f.write(chunk)
        except Exception as e:
            log.warning("Video download failed (%s): %s", item.source, e)
            return None

        if os.path.getsize(path) < 50 * 1024:
            log.warning("Downloaded file too small (<50KB), skipping")
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        log.info("⬇  Downloaded %s (%.1f MB)", item.source,
                 os.path.getsize(path) / (1024 * 1024))
        return path

    # ────────────────────────── ffmpeg pipeline ──────────────────────────

    def _ffmpeg_render(self, raw_path: str, item: VideoItem,
                       headline: str, category: str) -> Optional[str]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(
            self.output_dir, f"video_{category}_{ts}.mp4",
        )

        # Build a clean video filter graph — NO text overlays on the frame.
        # All headline / source / license / brand info now lives in the FB
        # caption only, so the video itself stays visually clean.
        tw, th = self.target_width, self.target_height
        vf_parts = [
            f"scale={tw}:{th}:force_original_aspect_ratio=decrease",
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black",
            f"fps={self.target_fps}",
        ]
        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", raw_path,
            "-t", str(self.max_duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", self.bitrate,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", self.audio_bitrate,
            "-movflags", "+faststart",
            out_path,
        ]
        log.info("🎞  Rendering watermarked clip → %s", os.path.basename(out_path))
        log.debug("ffmpeg: %s", " ".join(shlex.quote(c) for c in cmd))
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            log.error("ffmpeg timed out for %s", raw_path)
            return None
        except FileNotFoundError:
            log.error("ffmpeg binary missing")
            return None

        if res.returncode != 0:
            log.error("ffmpeg failed (rc=%d): %s",
                      res.returncode, (res.stderr or "")[-500:])
            try:
                os.remove(out_path)
            except OSError:
                pass
            return None
        log.info("✅ Video ready: %s (%.1f MB)", out_path,
                 os.path.getsize(out_path) / (1024 * 1024))
        return out_path

    # ────────────────────────── helpers ──────────────────────────

    def _font_arg(self) -> str:
        if self.font_path and os.path.isfile(self.font_path):
            return f"fontfile='{self.font_path}':"
        return ""

    @staticmethod
    def _truncate(s: str, n: int) -> str:
        s = (s or "").strip().replace("\n", " ")
        return s if len(s) <= n else s[: n - 1].rstrip() + "…"

    @staticmethod
    def _escape_drawtext(s: str) -> str:
        # ffmpeg drawtext requires escaping of these characters
        return (
            s.replace("\\", "\\\\")
             .replace(":", r"\:")
             .replace("'", r"\\'")
             .replace("%", r"\%")
        )
