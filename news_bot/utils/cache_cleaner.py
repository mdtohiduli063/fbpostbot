"""Advanced cache cleaner.

Periodically prunes:
  • generated images (TTL + max-disk-size)
  • daily report files (TTL)
  • events.jsonl (size cap with rotation)
  • posted.json (delegated to ArticleStore.prune)
  • old log files (TTL)
  • downloaded video clips (TTL + size cap)

Configurable via the ``cache`` block in ``config.json``.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .logger import get_logger

log = get_logger(__name__)


def _safe_listdir(path: str) -> List[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _human(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024  # type: ignore
    return f"{num_bytes:.1f}TB"


class CacheCleaner:
    """Clean caches based on TTL and disk-size budgets.

    All sizes in MB, all TTLs in hours."""

    def __init__(self, cfg: Dict[str, Any], paths: Dict[str, str]):
        self.cfg = cfg
        self.paths = paths
        self.last_run: float = 0.0
        self.run_every_minutes = int(cfg.get("run_every_minutes", 60))

        self.images_ttl_hours    = int(cfg.get("images_ttl_hours", 48))
        self.images_max_mb       = int(cfg.get("images_max_mb", 200))
        self.videos_ttl_hours    = int(cfg.get("videos_ttl_hours", 24))
        self.videos_max_mb       = int(cfg.get("videos_max_mb", 500))
        self.reports_ttl_days    = int(cfg.get("reports_ttl_days", 14))
        self.events_max_mb       = int(cfg.get("events_max_mb", 5))
        self.logs_ttl_days       = int(cfg.get("logs_ttl_days", 7))

    # ─────────────────────────── orchestrator ───────────────────────────

    def maybe_run(self) -> None:
        """Run cleanup if enough time has elapsed since last run."""
        elapsed_min = (time.time() - self.last_run) / 60.0
        if elapsed_min < self.run_every_minutes:
            return
        self.run()

    def run(self) -> Dict[str, int]:
        """Force a full sweep. Returns summary of bytes freed per area."""
        self.last_run = time.time()
        log.info("🧹 Cache cleaner: starting sweep")
        freed: Dict[str, int] = {}

        if d := self.paths.get("images_dir"):
            freed["images"] = self._prune_dir_ttl_size(
                d, self.images_ttl_hours, self.images_max_mb,
                allowed_ext=(".jpg", ".jpeg", ".png", ".webp"),
            )
        if d := self.paths.get("videos_dir"):
            freed["videos"] = self._prune_dir_ttl_size(
                d, self.videos_ttl_hours, self.videos_max_mb,
                allowed_ext=(".mp4", ".mov", ".webm", ".mkv", ".m4v"),
            )
        if d := self.paths.get("data_dir"):
            freed["reports"] = self._prune_old_reports(d, self.reports_ttl_days)
        if p := self.paths.get("events_path"):
            freed["events"] = self._cap_events_file(p, self.events_max_mb)
        if d := self.paths.get("logs_dir"):
            freed["logs"] = self._prune_old_logs(d, self.logs_ttl_days)

        total = sum(freed.values())
        log.info(
            "🧹 Cache cleaner: done — freed %s | %s",
            _human(total),
            ", ".join(f"{k}={_human(v)}" for k, v in freed.items()),
        )
        return freed

    # ─────────────────────────── strategies ───────────────────────────

    def _prune_dir_ttl_size(self, directory: str, ttl_hours: int,
                            max_mb: int, allowed_ext: Tuple[str, ...]) -> int:
        """Delete files older than TTL, then enforce a directory size cap
        (oldest first) until under ``max_mb``."""
        if not os.path.isdir(directory):
            return 0

        cutoff = time.time() - ttl_hours * 3600
        freed = 0
        files: List[Tuple[str, float, int]] = []  # (path, mtime, size)

        for name in _safe_listdir(directory):
            full = os.path.join(directory, name)
            if not os.path.isfile(full) or not name.lower().endswith(allowed_ext):
                continue
            mtime = _file_mtime(full)
            size = _file_size(full)
            if mtime < cutoff:
                try:
                    os.remove(full)
                    freed += size
                except OSError as e:
                    log.warning("Failed to delete %s: %s", full, e)
                continue
            files.append((full, mtime, size))

        # Enforce size cap
        max_bytes = max_mb * 1024 * 1024
        files.sort(key=lambda x: x[1])  # oldest first
        total = sum(s for _, _, s in files)
        idx = 0
        while total > max_bytes and idx < len(files):
            full, _, size = files[idx]
            try:
                os.remove(full)
                freed += size
                total -= size
            except OSError as e:
                log.warning("Failed to size-trim %s: %s", full, e)
            idx += 1

        return freed

    def _prune_old_reports(self, data_dir: str, ttl_days: int) -> int:
        """Delete report_YYYY-MM-DD.json files older than TTL."""
        if not os.path.isdir(data_dir):
            return 0
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
        freed = 0
        for name in _safe_listdir(data_dir):
            if not (name.startswith("report_") and name.endswith(".json")):
                continue
            try:
                date_str = name[len("report_"):-len(".json")]
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if date < cutoff:
                full = os.path.join(data_dir, name)
                size = _file_size(full)
                try:
                    os.remove(full)
                    freed += size
                except OSError as e:
                    log.warning("Failed to delete report %s: %s", full, e)
        return freed

    def _cap_events_file(self, path: str, max_mb: int) -> int:
        """If events.jsonl exceeds the cap, archive (rename .old) and start fresh."""
        if not os.path.isfile(path):
            return 0
        size = _file_size(path)
        max_bytes = max_mb * 1024 * 1024
        if size <= max_bytes:
            return 0
        archive = path + f".{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.old"
        try:
            shutil.move(path, archive)
            log.info("Rotated events log → %s", archive)
            # delete previous .old archives (keep only the latest two)
            self._keep_n_archives(os.path.dirname(path), prefix=os.path.basename(path) + ".", keep=2)
            return size
        except OSError as e:
            log.warning("Events rotation failed: %s", e)
            return 0

    def _keep_n_archives(self, directory: str, prefix: str, keep: int) -> None:
        items: List[Tuple[str, float]] = []
        for name in _safe_listdir(directory):
            if name.startswith(prefix) and name.endswith(".old"):
                full = os.path.join(directory, name)
                items.append((full, _file_mtime(full)))
        items.sort(key=lambda x: x[1], reverse=True)
        for full, _ in items[keep:]:
            try:
                os.remove(full)
            except OSError:
                pass

    def _prune_old_logs(self, logs_dir: str, ttl_days: int) -> int:
        """Delete rotated log backups older than TTL (keep current news_bot.log)."""
        if not os.path.isdir(logs_dir):
            return 0
        cutoff = time.time() - ttl_days * 86400
        freed = 0
        for name in _safe_listdir(logs_dir):
            if name == "news_bot.log":
                continue  # never delete the active log
            full = os.path.join(logs_dir, name)
            if not os.path.isfile(full):
                continue
            if _file_mtime(full) < cutoff:
                size = _file_size(full)
                try:
                    os.remove(full)
                    freed += size
                except OSError as e:
                    log.warning("Failed to delete log %s: %s", full, e)
        return freed
