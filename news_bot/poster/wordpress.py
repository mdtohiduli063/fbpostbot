"""Optional WordPress posting via REST API (Application Password auth)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

from ..utils.logger import get_logger

log = get_logger(__name__)


class WordPressPoster:
    """Creates a post on a WordPress site, with optional featured image upload."""

    def __init__(self, site_url: str, username: str, app_password: str,
                 default_status: str = "publish"):
        self.site_url = site_url.rstrip("/")
        self.auth = HTTPBasicAuth(username, app_password) if username and app_password else None
        self.default_status = default_status

    def is_ready(self) -> bool:
        return bool(self.site_url and self.auth)

    def post_article(self, title: str, content: str, image_path: Optional[str] = None,
                     categories: Optional[list] = None) -> Optional[int]:
        """Create a WP post. Returns post id or None."""
        if not self.is_ready():
            log.warning("WordPress not configured — skipping")
            return None

        media_id: Optional[int] = None
        if image_path:
            media_id = self._upload_media(image_path)

        payload: Dict[str, Any] = {
            "title": title,
            "content": content,
            "status": self.default_status,
        }
        if media_id:
            payload["featured_media"] = media_id
        if categories:
            payload["categories"] = categories

        try:
            resp = requests.post(
                f"{self.site_url}/wp-json/wp/v2/posts",
                json=payload,
                auth=self.auth,
                timeout=60,
            )
            if resp.status_code in (200, 201):
                pid = resp.json().get("id")
                log.info("WordPress post OK: %s", pid)
                return pid
            log.error("WP post failed (%d): %s", resp.status_code, resp.text[:300])
        except Exception as e:
            log.error("WP post error: %s", e)
        return None

    def _upload_media(self, image_path: str) -> Optional[int]:
        try:
            filename = os.path.basename(image_path)
            with open(image_path, "rb") as f:
                resp = requests.post(
                    f"{self.site_url}/wp-json/wp/v2/media",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Content-Type": "image/png",
                    },
                    data=f.read(),
                    auth=self.auth,
                    timeout=60,
                )
            if resp.status_code in (200, 201):
                return resp.json().get("id")
            log.warning("WP media upload failed (%d): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("WP media error: %s", e)
        return None
