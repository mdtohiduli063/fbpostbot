"""Async collector for copyright-free / public-domain news video clips.

Default sources (no API key required):
  • Voice of America (US Federal Government — public domain)
      RSS feeds with ``<enclosure type="video/mp4">`` items.
  • Wikimedia Commons category search (CC-BY-SA / CC0 / PD videos)
  • Internet Archive (PD / CC items, news-related collections)

Optional sources (require API keys via env vars):
  • Pexels videos       — PEXELS_API_KEY      (Pexels License — free use w/ attribution)
  • Pixabay videos      — PIXABAY_API_KEY     (Pixabay Content License — free use w/ attribution)
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from ..utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "BangaNewsBot/1.0 (+https://github.com/news-bot; contact@news-bot.local) "
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/json, text/html;q=0.9, */*;q=0.8",
}


@dataclass
class VideoItem:
    """Normalized representation of a copyright-free video clip."""
    title: str
    description: str
    video_url: str
    page_url: str
    source: str               # eg. "VOA News", "Wikimedia Commons"
    license_name: str         # eg. "Public Domain", "CC BY-SA 4.0"
    author: str = ""          # original creator
    published: Optional[datetime] = None
    duration_seconds: int = 0
    thumbnail_url: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def credit_line(self) -> str:
        """Compact credit line for caption + watermark overlay."""
        parts = [f"📡 সূত্র: {self.source}"]
        if self.author:
            parts.append(f"✍️ {self.author}")
        if self.license_name:
            parts.append(f"⚖️ {self.license_name}")
        return " · ".join(parts)


# ─────────────────────── default copyright-free sources ───────────────────────

# VOA RSS feeds with video enclosures (US public-domain content)
DEFAULT_VOA_FEEDS = [
    {"name": "VOA News",
     "url":  "https://www.voanews.com/api/zmgqoe$umi",
     "license": "Public Domain (US Federal Government)"},
    {"name": "VOA Bangla",
     "url":  "https://www.voabangla.com/api/zmgqoe$umi",
     "license": "Public Domain (US Federal Government)"},
]


class VideoCollector:
    """Pulls candidate video items from multiple copyright-free sources."""

    def __init__(self, cfg: Dict[str, Any], secrets: Dict[str, str]):
        self.cfg = cfg
        self.secrets = secrets
        self.timeout = aiohttp.ClientTimeout(total=int(cfg.get("timeout_seconds", 25)))
        self.max_per_source = int(cfg.get("max_per_source", 8))
        self.min_duration = int(cfg.get("min_duration_seconds", 8))
        self.max_duration = int(cfg.get("max_duration_seconds", 180))
        self.search_terms: List[str] = cfg.get("search_terms", [
            "Bangladesh", "Dhaka", "South Asia",
        ])
        self.sources_cfg: Dict[str, bool] = cfg.get("sources_enabled", {
            "voa": True,
            "wikimedia": True,
            "internet_archive": True,
            "pexels": True,
            "pixabay": True,
        })
        self.voa_feeds = cfg.get("voa_feeds", DEFAULT_VOA_FEEDS)

    # ──────────────────────────── main entrypoint ────────────────────────────

    async def collect_all(self) -> List[VideoItem]:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS,
                                         timeout=self.timeout) as session:
            tasks: List[asyncio.Future] = []
            if self.sources_cfg.get("voa", True):
                tasks.append(self._collect_voa(session))
            if self.sources_cfg.get("wikimedia", True):
                tasks.append(self._collect_wikimedia(session))
            if self.sources_cfg.get("internet_archive", True):
                tasks.append(self._collect_internet_archive(session))
            if self.sources_cfg.get("pexels", True) and self.secrets.get("pexels_api_key"):
                tasks.append(self._collect_pexels(session))
            if self.sources_cfg.get("pixabay", True) and self.secrets.get("pixabay_api_key"):
                tasks.append(self._collect_pixabay(session))

            results = await asyncio.gather(*tasks, return_exceptions=True)

        items: List[VideoItem] = []
        for res in results:
            if isinstance(res, Exception):
                log.warning("Video source failed: %s", res)
                continue
            items.extend(res)

        # Filter by duration window
        filtered: List[VideoItem] = []
        for it in items:
            if it.duration_seconds and (
                it.duration_seconds < self.min_duration or
                it.duration_seconds > self.max_duration
            ):
                continue
            filtered.append(it)

        log.info("🎬 Video collector: %d items (%d after duration filter)",
                 len(items), len(filtered))
        return filtered

    # ─────────────────────────────── VOA ───────────────────────────────

    async def _collect_voa(self, session: aiohttp.ClientSession) -> List[VideoItem]:
        items: List[VideoItem] = []
        for feed in self.voa_feeds:
            try:
                async with session.get(feed["url"]) as resp:
                    resp.raise_for_status()
                    body = await resp.read()
            except Exception as e:
                log.warning("VOA fetch failed for %s: %s", feed["name"], e)
                continue

            parsed = feedparser.parse(body)
            for entry in parsed.entries[: self.max_per_source]:
                video_url = self._extract_video_url_from_entry(entry)
                if not video_url:
                    continue

                title = (entry.get("title") or "").strip()
                desc_html = entry.get("summary") or entry.get("description") or ""
                desc = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)[:600]
                published = self._entry_datetime(entry)

                items.append(VideoItem(
                    title=title,
                    description=desc,
                    video_url=video_url,
                    page_url=(entry.get("link") or "").strip(),
                    source=feed["name"],
                    license_name=feed.get("license", "Public Domain"),
                    author="Voice of America",
                    published=published,
                    duration_seconds=int(entry.get("itunes_duration_seconds", 0)) or 0,
                    thumbnail_url=self._extract_thumbnail(entry),
                ))
        return items

    @staticmethod
    def _extract_video_url_from_entry(entry: Any) -> str:
        # 1. RSS enclosures
        for enc in entry.get("enclosures", []) or []:
            t = (enc.get("type") or "").lower()
            url = enc.get("href") or enc.get("url") or ""
            if "video" in t and url:
                return url
            if url.lower().endswith((".mp4", ".webm", ".mov", ".m4v")):
                return url
        # 2. media:content (Yahoo namespace, common in VOA feeds)
        for mc in entry.get("media_content", []) or []:
            url = mc.get("url") or ""
            t = (mc.get("type") or "").lower()
            if (url.lower().endswith((".mp4", ".webm", ".mov")) or
                    "video" in t):
                return url
        return ""

    @staticmethod
    def _extract_thumbnail(entry: Any) -> str:
        for mt in entry.get("media_thumbnail", []) or []:
            if mt.get("url"):
                return mt["url"]
        return ""

    @staticmethod
    def _entry_datetime(entry: Any) -> Optional[datetime]:
        for key in ("published_parsed", "updated_parsed"):
            tm = entry.get(key)
            if tm:
                try:
                    return datetime(*tm[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
        return None

    # ─────────────────────────── Wikimedia Commons ──────────────────────

    async def _collect_wikimedia(self, session: aiohttp.ClientSession) -> List[VideoItem]:
        """Use the MediaWiki API to find recent free-licensed video files."""
        items: List[VideoItem] = []
        api = "https://commons.wikimedia.org/w/api.php"
        for term in self.search_terms[:3]:
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{term} filetype:video",
                "gsrnamespace": "6",   # File: namespace — without this, no results
                "gsrlimit": str(self.max_per_source),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime|size|mediatype",
            }
            try:
                async with session.get(api, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.warning("Wikimedia search failed for '%s': %s", term, e)
                continue

            pages = ((data.get("query") or {}).get("pages") or {})
            for page in pages.values():
                infos = page.get("imageinfo") or []
                if not infos:
                    continue
                info = infos[0]
                url = info.get("url", "")
                if not url.lower().endswith((".webm", ".mp4", ".ogv", ".mov")):
                    continue
                meta = info.get("extmetadata") or {}
                license_short = (meta.get("LicenseShortName") or {}).get("value", "Free license")
                author_html = (meta.get("Artist") or {}).get("value", "")
                author = BeautifulSoup(author_html, "lxml").get_text(" ", strip=True) if author_html else ""
                title = page.get("title", "").replace("File:", "")
                desc_html = (meta.get("ImageDescription") or {}).get("value", "")
                desc = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)[:600]
                items.append(VideoItem(
                    title=title,
                    description=desc,
                    video_url=url,
                    page_url=f"https://commons.wikimedia.org/wiki/{quote_plus(page.get('title',''))}",
                    source="Wikimedia Commons",
                    license_name=license_short,
                    author=author or "Wikimedia contributors",
                ))
        return items

    # ─────────────────────────── Internet Archive ───────────────────────

    async def _collect_internet_archive(self,
                                        session: aiohttp.ClientSession) -> List[VideoItem]:
        items: List[VideoItem] = []
        api = "https://archive.org/advancedsearch.php"
        for term in self.search_terms[:2]:
            # Broader query — IA's licenseurl filter is too strict and excludes
            # many CC-licensed items whose license info lives in metadata only.
            q = (
                f'({term}) AND mediatype:movies AND '
                f'(licenseurl:*creativecommons* OR licenseurl:*publicdomain* '
                f'OR collection:opensource_movies OR collection:prelinger)'
            )
            params = {
                "q": q,
                "fl[]": "identifier,title,description,creator,licenseurl,date",
                "rows": str(self.max_per_source),
                "output": "json",
                "sort[]": "date desc",
            }
            try:
                async with session.get(api, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.warning("Internet Archive search failed for '%s': %s", term, e)
                continue

            for doc in (data.get("response") or {}).get("docs", []):
                ident = doc.get("identifier")
                if not ident:
                    continue
                # Resolve a playable mp4 file via metadata API
                video_url = await self._ia_resolve_video(session, ident)
                if not video_url:
                    continue
                title = (doc.get("title") or ident)[:200]
                desc = (doc.get("description") or "")
                if isinstance(desc, list):
                    desc = " ".join(map(str, desc))
                creator = doc.get("creator") or "Internet Archive contributors"
                if isinstance(creator, list):
                    creator = ", ".join(map(str, creator))
                license_url = doc.get("licenseurl", "") or ""
                license_name = "Creative Commons" if "creativecommons" in license_url else "Public Domain"

                items.append(VideoItem(
                    title=title,
                    description=str(desc)[:600],
                    video_url=video_url,
                    page_url=f"https://archive.org/details/{ident}",
                    source="Internet Archive",
                    license_name=license_name,
                    author=str(creator)[:120],
                ))
        return items

    @staticmethod
    async def _ia_resolve_video(session: aiohttp.ClientSession,
                                identifier: str) -> str:
        try:
            async with session.get(
                f"https://archive.org/metadata/{identifier}/files"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception:
            return ""
        files = data.get("result") or []
        # Prefer h.264 mp4 (small / 512kb / 360p / etc)
        preferred = [
            f for f in files
            if f.get("format", "").lower().endswith("mp4")
        ]
        preferred.sort(key=lambda f: int(float(f.get("size", 0) or 0)))
        for f in preferred:
            name = f.get("name")
            if name:
                return f"https://archive.org/download/{identifier}/{quote_plus(name)}"
        return ""

    # ─────────────────────────── Pexels ───────────────────────────

    async def _collect_pexels(self, session: aiohttp.ClientSession) -> List[VideoItem]:
        items: List[VideoItem] = []
        key = self.secrets.get("pexels_api_key")
        if not key:
            return items
        headers = {"Authorization": key}
        for term in self.search_terms[:2]:
            url = "https://api.pexels.com/videos/search"
            params = {"query": term, "per_page": str(self.max_per_source), "size": "medium"}
            try:
                async with session.get(url, headers=headers, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.warning("Pexels search failed: %s", e)
                continue
            for v in data.get("videos", []):
                files = v.get("video_files", [])
                # Pick the smallest mp4 around 720p
                mp4s = [f for f in files
                        if f.get("file_type", "").endswith("mp4")]
                mp4s.sort(key=lambda f: f.get("width", 0))
                pick = next((f for f in mp4s if (f.get("height") or 0) >= 480),
                            mp4s[0] if mp4s else None)
                if not pick:
                    continue
                user = (v.get("user") or {})
                items.append(VideoItem(
                    title=(v.get("url", "").rstrip("/").split("/")[-1] or "Pexels video")[:120],
                    description="",
                    video_url=pick["link"],
                    page_url=v.get("url", ""),
                    source="Pexels",
                    license_name="Pexels License (free use, attribution appreciated)",
                    author=user.get("name", "Pexels contributor"),
                    duration_seconds=int(v.get("duration", 0)),
                    thumbnail_url=v.get("image", ""),
                ))
        return items

    # ─────────────────────────── Pixabay ──────────────────────────

    async def _collect_pixabay(self, session: aiohttp.ClientSession) -> List[VideoItem]:
        items: List[VideoItem] = []
        key = self.secrets.get("pixabay_api_key")
        if not key:
            return items
        for term in self.search_terms[:2]:
            url = "https://pixabay.com/api/videos/"
            params = {"key": key, "q": term, "per_page": str(self.max_per_source)}
            try:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.warning("Pixabay search failed: %s", e)
                continue
            for v in data.get("hits", []):
                videos = v.get("videos", {})
                pick = (videos.get("medium") or videos.get("small") or
                        videos.get("tiny") or {})
                vid_url = pick.get("url")
                if not vid_url:
                    continue
                items.append(VideoItem(
                    title=(v.get("tags") or "Pixabay video")[:120],
                    description="",
                    video_url=vid_url,
                    page_url=v.get("pageURL", ""),
                    source="Pixabay",
                    license_name="Pixabay Content License (free use, attribution appreciated)",
                    author=v.get("user", "Pixabay contributor"),
                    duration_seconds=int(v.get("duration", 0)),
                    thumbnail_url=v.get("picture_id", ""),
                ))
        return items
