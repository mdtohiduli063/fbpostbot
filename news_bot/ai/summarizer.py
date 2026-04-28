"""Bangla summarizer powered by Gemini or OpenAI."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..collectors.rss_collector import Article
from ..utils.logger import get_logger
from .translator import Translator

log = get_logger(__name__)

# Gemini free tier ≈ 15 RPM. Enforce 5s spacing → safe headroom.
_MIN_SECONDS_BETWEEN_LLM_CALLS = 5.0


@dataclass
class Summary:
    """Final post-ready Bangla content."""
    headline: str
    body: str           # 2-4 line Bangla summary
    title: str          # click-worthy clean title
    hashtags: List[str]
    category: str
    source_url: str
    source_name: str

    def caption(self) -> str:
        """Build a Facebook/Telegram caption."""
        tags = " ".join(self.hashtags)
        return f"📰 {self.headline}\n\n{self.body}\n\n🔗 সূত্র: {self.source_name}\n\n{tags}"


PROMPT_TEMPLATE = """তুমি একজন অভিজ্ঞ বাংলা সংবাদ সম্পাদক। নিচের সংবাদটি পড়ে বাংলাদেশের ফেসবুক পাঠকদের জন্য পোস্ট তৈরি করো।

নিয়মাবলী:
- সহজ, পরিষ্কার, আবেগপ্রবণ বাংলায় লেখো
- ক্লিকবেইট নয়, কিন্তু আকর্ষণীয় শিরোনাম দাও
- সারাংশ ২ থেকে ৪ লাইনের মধ্যে রাখো
- ৩-৬টি প্রাসঙ্গিক হ্যাশট্যাগ যোগ করো (বাংলায়)
- কোনো ভুল তথ্য তৈরি করো না
- শুধুমাত্র বৈধ JSON আউটপুট দাও, অন্য কিছু না

বিভাগ: {category}
উৎস: {source}

মূল শিরোনাম:
{title}

মূল বিবরণ:
{body}

JSON ফরম্যাটে আউটপুট দাও:
{{
  "headline": "আকর্ষণীয় বাংলা শিরোনাম",
  "body": "২-৪ লাইনের সারাংশ",
  "title": "ক্লিক-যোগ্য পরিষ্কার টাইটেল",
  "hashtags": ["#ট্যাগ১", "#ট্যাগ২"]
}}"""


class Summarizer:
    """Provider-agnostic Bangla summarizer."""

    def __init__(self, cfg: Dict[str, Any], secrets: Dict[str, str]):
        self.cfg = cfg
        self.provider = cfg.get("provider", "gemini").lower()
        self.translator = Translator("bn") if cfg.get("translate_english_to_bangla", True) else None
        self.default_hashtags = cfg.get("default_hashtags", [])

        self._gemini = None
        self._openai = None
        self._last_call_ts: float = 0.0

        if self.provider == "gemini" and secrets.get("gemini_api_key"):
            try:
                import google.generativeai as genai
                genai.configure(api_key=secrets["gemini_api_key"])
                self._gemini = genai.GenerativeModel(cfg.get("gemini_model", "gemini-1.5-flash"))
                log.info("Gemini summarizer ready (%s)", cfg.get("gemini_model"))
            except Exception as e:
                log.error("Gemini init failed: %s", e)
        elif self.provider == "openai" and secrets.get("openai_api_key"):
            try:
                from openai import OpenAI
                self._openai = OpenAI(api_key=secrets["openai_api_key"])
                log.info("OpenAI summarizer ready (%s)", cfg.get("openai_model"))
            except Exception as e:
                log.error("OpenAI init failed: %s", e)
        else:
            log.warning("No AI provider configured — will use fallback summaries")

    def is_ready(self) -> bool:
        return self._gemini is not None or self._openai is not None

    def summarize(self, article: Article, category: str = "general") -> Optional[Summary]:
        """Generate Bangla summary; returns None if hard failure."""
        title = article.title
        body = article.summary or ""

        # Translate if mostly English
        if self.translator and article.is_english():
            t_title = self.translator.translate(title) or title
            t_body = self.translator.translate(body) if body else ""
            log.debug("Translated EN→BN for: %s", title[:60])
            title, body = t_title, t_body or body

        prompt = PROMPT_TEMPLATE.format(
            category=category, source=article.source, title=title, body=body[:1800],
        )

        raw = self._call_llm(prompt)
        if not raw:
            return self._fallback_summary(article, title, body, category)

        parsed = self._parse_json(raw)
        if not parsed:
            log.warning("Could not parse LLM output, using fallback")
            return self._fallback_summary(article, title, body, category)

        hashtags = parsed.get("hashtags") or []
        if not hashtags:
            hashtags = list(self.default_hashtags)

        return Summary(
            headline=parsed.get("headline", title)[:200],
            body=parsed.get("body", body[:300]),
            title=parsed.get("title", title)[:200],
            hashtags=[h if h.startswith("#") else f"#{h}" for h in hashtags][:6],
            category=category,
            source_url=article.link,
            source_name=article.source,
        )

    # ---------- internals ----------

    def _throttle(self) -> None:
        """Sleep to respect minimum spacing between LLM calls."""
        elapsed = time.time() - self._last_call_ts
        if elapsed < _MIN_SECONDS_BETWEEN_LLM_CALLS:
            time.sleep(_MIN_SECONDS_BETWEEN_LLM_CALLS - elapsed)
        self._last_call_ts = time.time()

    def _call_llm(self, prompt: str) -> Optional[str]:
        # Up to 3 attempts with exponential backoff for transient 429/5xx errors.
        for attempt in range(3):
            self._throttle()
            try:
                if self._gemini:
                    resp = self._gemini.generate_content(prompt)
                    return resp.text if hasattr(resp, "text") else str(resp)
                if self._openai:
                    resp = self._openai.chat.completions.create(
                        model=self.cfg.get("openai_model", "gpt-4o-mini"),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.7,
                    )
                    return resp.choices[0].message.content
                return None
            except Exception as e:
                msg = str(e)
                # Daily-quota errors won't recover within minutes — bail early.
                if "429" in msg and "quota" in msg.lower():
                    log.warning("Gemini quota hit (daily limit?) — using fallback: %s",
                                msg.split("\n")[0][:200])
                    return None
                log.warning("LLM attempt %d failed: %s", attempt + 1, msg.split("\n")[0][:200])
                time.sleep(2 ** attempt * 3)  # 3s, 6s, 12s
        log.error("LLM call failed after 3 attempts")
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        # Strip markdown code fences if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        # Extract first { ... } block as a safety net
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    def _fallback_summary(self, article: Article, title: str, body: str,
                          category: str) -> Summary:
        """When AI is unavailable, build a minimal usable post."""
        short_body = body[:280] if body else title
        return Summary(
            headline=title[:160],
            body=short_body,
            title=title[:160],
            hashtags=list(self.default_hashtags),
            category=category,
            source_url=article.link,
            source_name=article.source,
        )
