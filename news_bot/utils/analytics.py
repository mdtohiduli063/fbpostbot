"""Daily analytics: counts posts, sources, and writes a per-day report."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Optional


class Analytics:
    """Append-only event log + daily report writer."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.events_path = os.path.join(data_dir, "events.jsonl")

    def record(self, event: str, **fields: Any) -> None:
        rec = {"ts": datetime.utcnow().isoformat(), "event": event, **fields}
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def write_daily_report(self, date_str: Optional[str] = None) -> Optional[str]:
        """Aggregate events for a given date (YYYY-MM-DD) and write a JSON report."""
        date_str = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        if not os.path.exists(self.events_path):
            return None

        counts: Counter = Counter()
        sources: Counter = Counter()
        categories: Counter = Counter()
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not rec.get("ts", "").startswith(date_str):
                    continue
                counts[rec.get("event", "unknown")] += 1
                if "source" in rec:
                    sources[rec["source"]] += 1
                if "category" in rec:
                    categories[rec["category"]] += 1

        report: Dict[str, Any] = {
            "date": date_str,
            "events": dict(counts),
            "by_source": dict(sources),
            "by_category": dict(categories),
        }
        out_path = os.path.join(self.data_dir, f"report_{date_str}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return out_path
