"""Bangla summarizer powered by Gemini or OpenAI."""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from collectors.rss_collector import Article
from utils.logger import get_logger
from .translator import Translator

log = get_logger(__name__)

# Gemini free tier ≈ 15 RPM. Enforce 5s spacing → safe headroom.
_MIN_SECONDS_BETWEEN_LLM_CALLS = 5.0


CATEGORY_EMOJI: Dict[str, str] = {
    "breaking": "🚨", "politics": "🏛️", "cricket": "🏏",
    "entertainment": "🎬", "government": "📜", "price": "💰",
    "exam_jobs": "🎓", "tech": "💻", "world": "🌍",
    "sports": "🏆", "general": "📰",
}


@dataclass
class Summary:
    """Final post-ready Bangla content."""
    headline: str
    body: str           # 4-6 line Bangla summary
    title: str          # click-worthy clean title
    hashtags: List[str]
    category: str
    source_url: str
    source_name: str
    engagement: str = ""   # short follow-up question / call to comment

    def caption(self) -> str:
        """Build an audience-attractive Facebook caption.

        Layout (top → bottom):
          • single bold headline line with category emoji  (always first line!)
          • thin separator line
          • 4-6 line summary body
          • engagement hook with eye-catching emoji
          • source attribution
          • bot credit
          • hashtag block
        """
        emoji = CATEGORY_EMOJI.get(self.category, "📰")
        sep = "━━━━━━━━━━━━━━━━━━━━━"
        tags = " ".join(self.hashtags)
        # Headline always single line on top
        headline_line = f"{emoji} {self.headline.strip()}"

        parts: List[str] = [
            headline_line,
            sep,
            self.body.strip(),
        ]
        if self.engagement:
            parts += ["", self.engagement]
        parts += [
            "",
            f"📡 সূত্র: {self.source_name}",
            f"🔗 মূল সংবাদ: {self.source_url}",
            "",
            "🤖 BOT BY TOHIDUL",
            "",
            tags,
        ]
        return "\n".join(parts)


PROMPT_TEMPLATE = """তুমি একজন অভিজ্ঞ বাংলা সংবাদ সম্পাদক এবং ফেসবুক ভাইরাল পোস্ট লেখক।
তোমার কাজ এমন একটি পোস্ট বানানো যা পড়েই পাঠক থামতে বাধ্য হবে।

নিয়মাবলী:
- শিরোনাম অবশ্যই **এক লাইনে**, সর্বোচ্চ ৮-১১ শব্দ — শক্তিশালী, আবেগপ্রবণ, কৌতূহল জাগানো
- শিরোনামে কখনো ক্লিকবেইট নয়, কিন্তু পাঠকের মনে প্রশ্ন/উত্তেজনা তৈরি হবে
- সারাংশ ৪-৬ লাইন (৭০-১২০ শব্দ) — প্রতিটি লাইন একটি স্বতন্ত্র তথ্য বহন করবে
- কে, কী, কোথায়, কখন, কেন — এই ৫টি প্রশ্নের উত্তর সারাংশে থাকতেই হবে
- ভাষা সহজ, প্রাণবন্ত, আবেগপ্রবণ — ফেসবুকে যেমন পাঠক পড়ে
- ৬-৮টি প্রাসঙ্গিক হ্যাশট্যাগ (বেশিরভাগ বাংলা, ২-৩টি ইংরেজি ট্রেন্ডিং)
- শেষে একটি ছোট, আকর্ষণীয় ক্লোজিং লাইন — পাঠককে পেজ ফলো করতে / শেয়ার করতে / আপডেট থাকতে অনুপ্রাণিত করবে; কখনোই কমেন্ট চাইবে না, কোনো প্রশ্ন করবে না
- কোনো ভুল তথ্য বানিয়ো না, মূল সংবাদের বাইরে যেও না
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
  "body": "৪-৬ লাইনের বিস্তারিত সারাংশ যেখানে কে, কী, কোথায়, কেন তথ্য থাকবে",
  "title": "ক্লিক-যোগ্য পরিষ্কার টাইটেল",
  "engagement": "একটি ছোট ফলো/শেয়ার আমন্ত্রণ লাইন (কমেন্ট চাইবে না)",
  "hashtags": ["#ট্যাগ১", "#ট্যাগ২", "#ট্যাগ৩"]
}}"""


class Summarizer:
    """Provider-agnostic Bangla summarizer."""

    def __init__(self, cfg: Dict[str, Any], secrets: Dict[str, str]):
        self.cfg = cfg
        self.provider = cfg.get("provider", "gemini").lower()
        self.translator = Translator("bn") if cfg.get("translate_english_to_bangla", True) else None
        self.default_hashtags = cfg.get("default_hashtags", [])
        self.category_hashtags: Dict[str, List[str]] = cfg.get("category_hashtags", {})
        self.max_hashtags = int(cfg.get("max_hashtags", 8))

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

        hashtags = self._merge_hashtags(parsed.get("hashtags") or [], category)

        return Summary(
            headline=parsed.get("headline", title)[:200],
            body=parsed.get("body", body[:600]),
            title=parsed.get("title", title)[:200],
            hashtags=hashtags,
            category=category,
            source_url=article.link,
            source_name=article.source,
            engagement=(parsed.get("engagement") or "").strip()[:200],
        )

    def _merge_hashtags(self, ai_tags: List[str], category: str) -> List[str]:
        """Combine AI-suggested + per-category curated + global default tags."""
        out: List[str] = []
        seen: set = set()
        # 1. AI tags first (most specific to the actual story)
        for t in ai_tags:
            tag = t if t.startswith("#") else f"#{t}"
            if tag.lower() not in seen:
                out.append(tag); seen.add(tag.lower())
        # 2. Category-curated tags
        for t in self.category_hashtags.get(category, []):
            tag = t if t.startswith("#") else f"#{t}"
            if tag.lower() not in seen:
                out.append(tag); seen.add(tag.lower())
        # 3. Global defaults to fill remaining slots
        for t in self.default_hashtags:
            tag = t if t.startswith("#") else f"#{t}"
            if tag.lower() not in seen:
                out.append(tag); seen.add(tag.lower())
        return out[:self.max_hashtags]

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

    # Closing call-to-action lines — never asks for comments.
    _CLOSERS = (
        "🔔 প্রতিদিনের গুরুত্বপূর্ণ খবর সবার আগে পেতে পেজটি ফলো করে রাখুন।",
        "📤 খবরটি গুরুত্বপূর্ণ মনে হলে প্রিয়জনদের সাথে শেয়ার করুন।",
        "✨ সঠিক ও দ্রুত সংবাদ পেতে আমাদের সাথে থাকুন।",
        "🚀 এমন আরও খবরের আপডেট পেতে পেজটি ফলো করুন।",
        "🌟 পরিবার-বন্ধুদের সাথে শেয়ার করে সবাইকে জানিয়ে দিন।",
        "🔥 সর্বশেষ সংবাদ মিস করতে না চাইলে পেজটি ফলো দিয়ে রাখুন।",
    )

    @classmethod
    def _pick_closer(cls) -> str:
        return random.choice(cls._CLOSERS)

    # Category-specific Bangla intro lines for the fallback summary
    _FALLBACK_INTROS: Dict[str, str] = {
        "breaking":      "🚨 জরুরি খবর — ",
        "politics":      "🏛️ রাজনৈতিক খবর: ",
        "cricket":       "🏏 ক্রিকেট আপডেট: ",
        "sports":        "🏆 খেলাধুলার খবর: ",
        "entertainment": "🎬 বিনোদন জগতের খবর: ",
        "government":    "📜 সরকারি ঘোষণা: ",
        "price":         "💰 দাম-দর সংক্রান্ত খবর: ",
        "exam_jobs":     "🎓 পরীক্ষা ও চাকরির খবর: ",
        "tech":          "💻 প্রযুক্তি জগতের খবর: ",
        "world":         "🌍 আন্তর্জাতিক খবর: ",
        "general":       "📰 সর্বশেষ খবর: ",
    }

    @staticmethod
    def _split_sentences_bn(text: str) -> List[str]:
        """Split Bangla / mixed text into clean sentences using ।, ., ?, !"""
        # Normalize whitespace + remove obvious junk (read more, source tags, urls)
        cleaned = re.sub(r"https?://\S+", "", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Drop common boilerplate suffixes
        cleaned = re.sub(r"(বিস্তারিত পড়ুন|আরও পড়ুন|Read more|Click here)[\s:.।]*$",
                         "", cleaned, flags=re.IGNORECASE)
        # Split, keep pieces longer than 15 chars
        parts = re.split(r"(?<=[।.!?])\s+", cleaned)
        return [p.strip() for p in parts if len(p.strip()) > 15]

    def _fallback_summary(self, article: Article, title: str, body: str,
                          category: str) -> Summary:
        """When AI is unavailable, build a richer fallback post.

        Strategy: take first 2–3 meaningful sentences from the RSS body
        (not just a char-count slice) and prepend a category-specific intro
        so the body never duplicates the headline word-for-word.
        """
        clean_title = re.sub(r"\s+", " ", title).strip()[:200]

        sentences = self._split_sentences_bn(body) if body else []
        # Drop the first sentence if it's just the title repeated
        if sentences and sentences[0].rstrip("।.!?").strip() == clean_title.rstrip("।.!?").strip():
            sentences = sentences[1:]

        if sentences:
            picked: List[str] = []
            total = 0
            for s in sentences[:5]:
                if total + len(s) > 500:
                    break
                picked.append(s)
                total += len(s)
            short_body = " ".join(picked) if picked else sentences[0][:500]
        else:
            # No usable body — synthesize a minimal informative line
            short_body = f"{clean_title}। বিস্তারিত পড়তে নিচের লিংকে চাপুন।"

        intro = self._FALLBACK_INTROS.get(category, self._FALLBACK_INTROS["general"])
        # Avoid double-emoji if body already begins with one
        if not short_body.startswith(("🚨", "🏛", "🏏", "🎬", "📜", "💰", "🎓", "💻", "🌍", "🏆", "📰")):
            short_body = intro + short_body

        return Summary(
            headline=clean_title,
            body=short_body,
            title=clean_title,
            hashtags=self._merge_hashtags([], category),
            category=category,
            source_url=article.link,
            source_name=article.source,
            engagement=self._pick_closer(),
        )
