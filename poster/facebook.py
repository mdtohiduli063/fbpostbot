"""Facebook Page posting via Graph API."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from utils.logger import get_logger

log = get_logger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


class FacebookPoster:
    """Post photo + caption to a Facebook Page, with optional first comment."""

    def __init__(self, page_id: str, access_token: str, auto_first_comment: bool = True):
        self.page_id = page_id
        self.token = access_token
        self.auto_first_comment = auto_first_comment

    def is_ready(self) -> bool:
        return bool(self.page_id and self.token)

    def post_photo(self, image_path: str, caption: str,
                   source_url: Optional[str] = None) -> Optional[str]:
        """Upload photo + caption. Returns post_id (or None on failure)."""
        if not self.is_ready():
            log.warning("Facebook not configured — skipping post")
            return None

        url = f"{GRAPH_API}/{self.page_id}/photos"

        for attempt in range(3):
            try:
                with open(image_path, "rb") as f:
                    files = {"source": f}
                    data = {"caption": caption, "access_token": self.token}
                    resp = requests.post(url, files=files, data=data, timeout=60)
                if resp.status_code == 200:
                    body = resp.json()
                    post_id = body.get("post_id") or body.get("id")
                    log.info("Facebook post OK: %s", post_id)
                    if self.auto_first_comment and source_url and post_id:
                        self._comment(post_id, f"🔗 মূল সংবাদ: {source_url}")
                    return post_id
                log.warning("FB attempt %d failed (%d): %s",
                            attempt + 1, resp.status_code, resp.text[:300])
            except Exception as e:
                log.warning("FB attempt %d error: %s", attempt + 1, e)
            time.sleep(2 ** attempt)

        log.error("Facebook post failed after retries")
        return None

    def _comment(self, post_id: str, message: str) -> None:
        try:
            url = f"{GRAPH_API}/{post_id}/comments"
            resp = requests.post(
                url,
                data={"message": message, "access_token": self.token},
                timeout=30,
            )
            if resp.status_code == 200:
                log.info("First comment added on %s", post_id)
            else:
                log.warning("Comment failed (%d): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("Comment error: %s", e)
