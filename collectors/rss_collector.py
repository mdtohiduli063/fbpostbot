"""Async RSS + scraping fallback collector."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.8",
}


@dataclass
class Article:
    """Normalized article representation."""
    title: str
    link: str
    summary: str
    published: Optional[datetime]
    source: str
    raw_html: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def is_english(self) -> bool:
        """Heuristic: if more than 60% of letters are ASCII, treat as English."""
        text = f"{self.title} {self.summary}"
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False
        ascii_letters = [c for c in letters if c.isascii()]
        return (len(ascii_letters) / len(letters)) > 0.6


class RSSCollector:
    """Fetch articles from configured RSS sources concurrently."""

    def __init__(self, sources: List[Dict[str, Any]], max_per_source: int = 15,
                 timeout_seconds: int = 20):
        self.sources = [s for s in sources if s.get("enabled", True)]
        self.max_per_source = max_per_source
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def collect_all(self) -> List[Article]:
        """Fetch all enabled sources in parallel."""
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=self.timeout) as session:
            tasks = [self._fetch_source(session, src) for src in self.sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: List[Article] = []
        for src, res in zip(self.sources, results):
            if isinstance(res, Exception):
                log.warning("Source '%s' failed: %s", src.get("name"), res)
                continue
            articles.extend(res)
        log.info("Collected %d articles from %d sources", len(articles), len(self.sources))
        return articles

    async def _fetch_source(self, session: aiohttp.ClientSession,
                            src: Dict[str, Any]) -> List[Article]:
        name = src["name"]
        url = src["url"]
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content = await resp.read()
        except Exception as e:
            log.warning("Fetch failed for %s: %s", name, e)
            return []

        # Try RSS first
        feed = feedparser.parse(content)
        items: List[Article] = []
        if feed.entries:
            for entry in feed.entries[: self.max_per_source]:
                items.append(self._entry_to_article(entry, name))
        else:
            # Fallback: scrape <a> headlines from HTML
            log.info("No RSS entries for %s, falling back to HTML scrape", name)
            items = self._scrape_html(content, name, url)

        return items

    @staticmethod
    def _entry_to_article(entry: Any, source: str) -> Article:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary_html = entry.get("summary") or entry.get("description") or ""
        summary_text = BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True)

        published: Optional[datetime] = None
        for key in ("published_parsed", "updated_parsed"):
            tm = entry.get(key)
            if tm:
                try:
                    published = datetime(*tm[:6], tzinfo=timezone.utc)
                    break
                except (TypeError, ValueError):
                    continue

        return Article(
            title=title,
            link=link,
            summary=summary_text[:1500],
            published=published,
            source=source,
            raw_html=summary_html,
        )

    def _scrape_html(self, content: bytes, source: str, base_url: str) -> List[Article]:
        soup = BeautifulSoup(content, "lxml")
        articles: List[Article] = []
        for a in soup.select("a")[: self.max_per_source * 4]:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if len(title) < 25 or not href:
                continue
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            articles.append(Article(
                title=title, link=href, summary="", published=None, source=source,
            ))
            if len(articles) >= self.max_per_source:
                break
        return articles
