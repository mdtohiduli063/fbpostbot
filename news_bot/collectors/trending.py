"""Score articles by viral keywords + recency to detect trending/breaking news."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .rss_collector import Article


class TrendingScorer:
    """Scores articles based on configured viral keywords and recency."""

    def __init__(self, keywords_by_category: Dict[str, List[str]],
                 enabled_categories: Dict[str, bool]):
        # Lowercased keyword index per enabled category
        self.index: Dict[str, List[str]] = {}
        for cat, kws in keywords_by_category.items():
            if enabled_categories.get(cat, True):
                self.index[cat] = [k.lower() for k in kws]

    def score(self, article: Article) -> Tuple[float, str]:
        """Return (score, detected_category)."""
        text = f"{article.title} {article.summary}".lower()
        best_cat = "general"
        best_hits = 0

        for cat, kws in self.index.items():
            hits = sum(1 for k in kws if k in text)
            # 'breaking' weighted higher
            weight = 2.0 if cat == "breaking" else 1.0
            weighted = hits * weight
            if weighted > best_hits:
                best_hits = weighted
                best_cat = cat

        # Recency bonus: newer = higher score (decays over 24h)
        recency_bonus = 0.0
        if article.published:
            age_h = (datetime.now(timezone.utc) - article.published).total_seconds() / 3600
            if age_h < 24:
                recency_bonus = max(0.0, 3.0 - (age_h / 8.0))

        return (best_hits + recency_bonus, best_cat)

    def rank(self, articles: List[Article]) -> List[Tuple[Article, float, str]]:
        """Return articles sorted by score descending."""
        scored = [(a, *self.score(a)) for a in articles]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
