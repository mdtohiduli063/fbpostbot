"""Duplicate detection using normalized title hashes + URL hashes."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, List

from .rss_collector import Article


_PUNCT_RE = re.compile(r"[^\w\u0980-\u09FF\s]", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Keeps Bangla unicode block (\u0980-\u09FF) and word chars.
    """
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def article_key(article: Article) -> str:
    """Stable hash that identifies an article by URL or normalized title."""
    base = article.link.strip() or normalize(article.title)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def title_key(article: Article) -> str:
    """Hash of normalized title (catches reposts of same story across sources)."""
    return hashlib.sha1(normalize(article.title).encode("utf-8")).hexdigest()


class Deduplicator:
    """Filters out articles already seen (in-memory + persistent store)."""

    def __init__(self, seen_keys: Iterable[str] = ()):
        self._seen = set(seen_keys)

    def filter(self, articles: List[Article]) -> List[Article]:
        unique: List[Article] = []
        local_seen = set()
        for art in articles:
            if not art.title or not art.link:
                continue
            k1 = article_key(art)
            k2 = title_key(art)
            if k1 in self._seen or k2 in self._seen:
                continue
            if k1 in local_seen or k2 in local_seen:
                continue
            local_seen.add(k1)
            local_seen.add(k2)
            unique.append(art)
        return unique

    def mark_seen(self, article: Article) -> None:
        self._seen.add(article_key(article))
        self._seen.add(title_key(article))
