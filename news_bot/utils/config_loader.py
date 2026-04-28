"""Load config.json and merge environment variables."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from dotenv import load_dotenv


def load_config(path: str = "config.json") -> Dict[str, Any]:
    """Load JSON config file and overlay secrets from environment."""
    load_dotenv()  # picks up .env if present

    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = json.load(f)

    # Inject secrets from environment so config.json stays clean of credentials
    cfg.setdefault("secrets", {})
    cfg["secrets"].update({
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "facebook_page_access_token": os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", ""),
        "facebook_page_id": os.getenv("FACEBOOK_PAGE_ID", "")
            or cfg.get("facebook", {}).get("page_id", ""),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_channel_id": os.getenv("TELEGRAM_CHANNEL_ID", "")
            or cfg.get("telegram", {}).get("channel_id", ""),
        "wordpress_url": os.getenv("WORDPRESS_URL", "")
            or cfg.get("wordpress", {}).get("site_url", ""),
        "wordpress_username": os.getenv("WORDPRESS_USERNAME", ""),
        "wordpress_app_password": os.getenv("WORDPRESS_APP_PASSWORD", ""),
    })

    return cfg
