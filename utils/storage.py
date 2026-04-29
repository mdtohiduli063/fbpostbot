"""Lightweight JSON-file persistence for posted/seen articles."""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Set


class ArticleStore:
    """Tracks posted article hashes to prevent duplicates across restarts."""

    def __init__(self, data_dir: str = "data", ttl_hours: int = 72):
        self.data_dir = data_dir
        self.ttl_seconds = ttl_hours * 3600
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "posted.json")
        self._data: Dict[str, float] = self._load()

    def _load(self) -> Dict[str, float]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)

    def prune(self) -> None:
        """Drop entries older than TTL."""
        cutoff = time.time() - self.ttl_seconds
        self._data = {k: v for k, v in self._data.items() if v >= cutoff}
        self._save()

    def has(self, key: str) -> bool:
        return key in self._data

    def add(self, key: str) -> None:
        self._data[key] = time.time()
        self._save()

    def all_keys(self) -> Set[str]:
        return set(self._data.keys())
