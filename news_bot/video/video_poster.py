"""Upload a watermarked video to a Facebook Page with full credit caption."""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

from ..utils.logger import get_logger
from .video_collector import VideoItem

log = get_logger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


class VideoPoster:
    """Post videos to a Facebook Page via Graph API ``/videos`` edge."""

    def __init__(self, page_id: str, access_token: str):
        self.page_id = page_id
        self.token = access_token

    def is_ready(self) -> bool:
        return bool(self.page_id and self.token)

    def post_video(self, video_path: str, item: VideoItem,
                   caption: str) -> Optional[str]:
        """Upload `video_path` as a Page post. Returns the FB video id."""
        if not self.is_ready():
            log.warning("Facebook (video) not configured — skipping")
            return None
        if not (video_path and os.path.isfile(video_path)):
            log.warning("Video file missing: %s", video_path)
            return None

        url = f"{GRAPH_API}/{self.page_id}/videos"
        # Single-request upload — fine for Facebook's <1GB / <20min limit
        for attempt in range(3):
            try:
                with open(video_path, "rb") as f:
                    files = {"source": f}
                    data = {
                        "access_token": self.token,
                        "description": caption,
                        "title": item.title[:120],
                    }
                    resp = requests.post(url, files=files, data=data, timeout=600)
                if resp.status_code == 200:
                    body = resp.json()
                    vid = body.get("id") or body.get("video_id")
                    log.info("📺 Facebook video posted: %s", vid)
                    return str(vid) if vid else None
                log.warning("Video upload attempt %d failed (%d): %s",
                            attempt + 1, resp.status_code, resp.text[:300])
            except Exception as e:
                log.warning("Video upload attempt %d error: %s", attempt + 1, e)
            time.sleep(2 ** attempt * 3)
        log.error("Facebook video upload failed after retries")
        return None
