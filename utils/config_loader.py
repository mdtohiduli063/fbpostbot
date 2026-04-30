"""Load ``config.json`` — the single source of truth for the bot.

All API keys, tokens and tunables live inside ``config.json``. There is
**no** ``.env`` file and **no** environment-variable lookups: drop your
keys into the ``credentials`` block, run the bot, done.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict


# Every secret the rest of the codebase may ask for. Anything missing in
# ``credentials`` simply becomes "" so the related feature stays disabled.
_SECRET_KEYS = (
    "gemini_api_key",
    "openai_api_key",
    "facebook_page_access_token",
    "facebook_page_id",
    "pexels_api_key",
    "pixabay_api_key",
)


def load_config(path: str = "config.json") -> Dict[str, Any]:
    """Load JSON config and expose credentials under ``cfg["secrets"]``."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.json into the "
            f"project root and fill in the 'credentials' block."
        )

    with open(path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = json.load(f)

    creds_block = cfg.get("credentials", {}) or {}
    cfg["secrets"] = {
        key: str(creds_block.get(key, "") or "").strip()
        for key in _SECRET_KEYS
    }
    return cfg
