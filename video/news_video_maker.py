"""Build a 15–20 s vertical-square (1080×1080) video from a generated news
image, with a randomly chosen background-music track from the ``audio/``
folder.

Pipeline (per post):
  1. Pick a random duration ∈ [duration_min_seconds, duration_max_seconds].
  2. Pick a random audio file from the configured audio dir
     (``.mp3``, ``.m4a``, ``.wav``, ``.aac``, ``.ogg``).
     If no file is present, render a silent video instead.
  3. Run ffmpeg:
        - loop the still image at the target FPS
        - apply a slow Ken-Burns style zoom for movement
        - trim audio to clip length, fade-in / fade-out
        - encode H.264 + AAC MP4 ready for Facebook upload
"""
from __future__ import annotations

import os
import random
import shlex
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

log = get_logger(__name__)

_AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")


class NewsVideoMaker:
    """Convert a single news image + bg music → short FB-ready MP4."""

    def __init__(self, cfg: Dict[str, Any], output_dir: str, audio_dir: str):
        self.duration_min = max(5, int(cfg.get("duration_min_seconds", 15)))
        self.duration_max = max(self.duration_min,
                                int(cfg.get("duration_max_seconds", 20)))
        self.target_w = int(cfg.get("target_width", 1080))
        self.target_h = int(cfg.get("target_height", 1080))
        self.target_fps = int(cfg.get("target_fps", 30))
        self.video_bitrate = cfg.get("video_bitrate", "2200k")
        self.audio_bitrate = cfg.get("audio_bitrate", "160k")
        self.zoom = max(0.0, float(cfg.get("zoom_strength", 0.10)))
        self.fade_seconds = max(0.1, float(cfg.get("audio_fade_seconds", 1.2)))
        self.audio_volume = float(cfg.get("audio_volume", 0.85))
        self.timeout_seconds = int(cfg.get("ffmpeg_timeout_seconds", 180))

        self.output_dir = output_dir
        self.audio_dir = audio_dir
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)

        self._has_ffmpeg = bool(shutil.which("ffmpeg"))
        if not self._has_ffmpeg:
            log.warning("ffmpeg not found — NewsVideoMaker disabled")

    # ───────────────────────────── public ─────────────────────────────

    def is_ready(self) -> bool:
        return self._has_ffmpeg

    def list_audio_tracks(self) -> List[str]:
        if not os.path.isdir(self.audio_dir):
            return []
        return sorted(
            os.path.join(self.audio_dir, f)
            for f in os.listdir(self.audio_dir)
            if f.lower().endswith(_AUDIO_EXTS) and not f.startswith(".")
        )

    def make(self, image_path: str, category: str = "general",
             duration_seconds: Optional[int] = None) -> Optional[str]:
        """Produce a 15–20 s MP4 from the news image + random BG music."""
        if not self._has_ffmpeg:
            log.error("ffmpeg missing — cannot build news video")
            return None
        if not (image_path and os.path.isfile(image_path)):
            log.error("News image not found: %s", image_path)
            return None

        duration = (int(duration_seconds) if duration_seconds
                    else random.randint(self.duration_min, self.duration_max))
        audio_path = self._pick_audio()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = os.path.join(self.output_dir,
                                f"news_{category}_{ts}.mp4")

        cmd = self._build_ffmpeg_cmd(image_path, audio_path, duration, out_path)

        log.info("🎞  Building news video: %ds, audio=%s",
                 duration,
                 os.path.basename(audio_path) if audio_path else "none (silent)")
        log.debug("ffmpeg: %s", " ".join(shlex.quote(c) for c in cmd))

        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.error("ffmpeg timed out building news video")
            self._safe_rm(out_path)
            return None
        except FileNotFoundError:
            log.error("ffmpeg binary missing")
            return None

        if res.returncode != 0:
            log.error("ffmpeg failed (rc=%d): %s",
                      res.returncode, (res.stderr or "")[-700:])
            self._safe_rm(out_path)
            return None

        log.info("✅ News video ready: %s (%.2f MB)", out_path,
                 os.path.getsize(out_path) / (1024 * 1024))
        return out_path

    # ───────────────────────────── internals ─────────────────────────────

    def _pick_audio(self) -> Optional[str]:
        tracks = self.list_audio_tracks()
        return random.choice(tracks) if tracks else None

    def _build_ffmpeg_cmd(self, image_path: str, audio_path: Optional[str],
                          duration: int, out_path: str) -> List[str]:
        total_frames = max(1, int(duration * self.target_fps))
        # Ken-Burns: zoom from 1.00 → 1.0+zoom across the whole clip
        if self.zoom > 0:
            zoom_step = self.zoom / total_frames
            big_w = self.target_w * 4
            big_h = self.target_h * 4
            vf = (
                f"scale={big_w}:{big_h}:flags=lanczos,"
                f"zoompan=z='min(zoom+{zoom_step:.6f},{1.0 + self.zoom:.4f})'"
                f":d={total_frames}:s={self.target_w}x{self.target_h}"
                f":fps={self.target_fps},setsar=1"
            )
        else:
            vf = (
                f"scale={self.target_w}:{self.target_h}:flags=lanczos,"
                f"fps={self.target_fps},setsar=1"
            )

        cmd: List[str] = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", image_path,
        ]
        if audio_path:
            cmd += ["-i", audio_path]

        cmd += [
            "-t", f"{duration}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-b:v", self.video_bitrate, "-pix_fmt", "yuv420p",
            "-r", str(self.target_fps),
        ]

        if audio_path:
            fade = max(0.1, min(self.fade_seconds, duration / 3))
            af = (
                f"volume={self.audio_volume:.2f},"
                f"afade=t=in:st=0:d={fade:.2f},"
                f"afade=t=out:st={max(0.0, duration - fade):.2f}:d={fade:.2f},"
                f"atrim=0:{duration}"
            )
            cmd += [
                "-af", af,
                "-c:a", "aac", "-b:a", self.audio_bitrate, "-ac", "2",
                "-shortest",
            ]
        else:
            cmd += ["-an"]

        cmd += ["-movflags", "+faststart", out_path]
        return cmd

    @staticmethod
    def _safe_rm(path: str) -> None:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
