"""Telegram channel posting via Bot API (no extra deps — pure HTTP)."""
from __future__ import annotations

import time
from typing import Optional

import requests

from ..utils.logger import get_logger

log = get_logger(__name__)


class TelegramPoster:
    """Sends image + caption to a Telegram channel."""

    def __init__(self, bot_token: str, channel_id: str):
        self.token = bot_token
        self.channel_id = channel_id
        self.api = f"https://api.telegram.org/bot{bot_token}" if bot_token else ""

    def is_ready(self) -> bool:
        return bool(self.token and self.channel_id)

    def post_photo(self, image_path: str, caption: str) -> Optional[int]:
        """Send photo. Returns message_id or None."""
        if not self.is_ready():
            log.warning("Telegram not configured — skipping post")
            return None

        url = f"{self.api}/sendPhoto"
        # Telegram caption limit is 1024 chars
        capped = caption[:1020] + "…" if len(caption) > 1024 else caption

        for attempt in range(3):
            try:
                with open(image_path, "rb") as f:
                    files = {"photo": f}
                    data = {"chat_id": self.channel_id, "caption": capped}
                    resp = requests.post(url, files=files, data=data, timeout=60)
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("ok"):
                        msg_id = body["result"]["message_id"]
                        log.info("Telegram post OK: %s", msg_id)
                        return msg_id
                log.warning("TG attempt %d failed (%d): %s",
                            attempt + 1, resp.status_code, resp.text[:300])
            except Exception as e:
                log.warning("TG attempt %d error: %s", attempt + 1, e)
            time.sleep(2 ** attempt)

        log.error("Telegram post failed after retries")
        return None
