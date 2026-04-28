"""Load config.json and resolve credentials.

Credentials precedence (highest first):
  1. Environment variable (e.g. GEMINI_API_KEY) — useful for VPS deployment
  2. ``credentials.<key>`` block inside config.json — useful when the user
     prefers to keep everything in a single file
  3. Empty string (feature stays disabled)
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from dotenv import load_dotenv


# Maps the secret key used inside the bot → matching env-var name
_SECRET_ENV_MAP: Dict[str, str] = {
    "gemini_api_key":              "GEMINI_API_KEY",
    "openai_api_key":              "OPENAI_API_KEY",
    "facebook_page_access_token":  "FACEBOOK_PAGE_ACCESS_TOKEN",
    "facebook_page_id":            "FACEBOOK_PAGE_ID",
    "pexels_api_key":              "PEXELS_API_KEY",
    "pixabay_api_key":             "PIXABAY_API_KEY",
}


def load_config(path: str = "config.json") -> Dict[str, Any]:
    """Load JSON config file and resolve credentials from env or config.json."""
    load_dotenv()  # picks up .env if present (optional)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = json.load(f)

    creds_block = cfg.get("credentials", {}) or {}
    cfg["secrets"] = {}
    for key, env_name in _SECRET_ENV_MAP.items():
        env_val = os.getenv(env_name, "").strip()
        cfg_val = str(creds_block.get(key, "") or "").strip()
        cfg["secrets"][key] = env_val or cfg_val

    return cfg
