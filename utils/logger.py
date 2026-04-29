"""Centralized logging with rotating file handler."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


_INITIALIZED = False


def setup_logging(logs_dir: str = "logs", level: str = "INFO",
                  max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5) -> None:
    """Configure root logger with console + rotating file handler.

    Safe to call multiple times — only initializes once.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    os.makedirs(logs_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Rotating file handler
    fh = RotatingFileHandler(
        os.path.join(logs_dir, "news_bot.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Quiet down noisy third-party libs
    for noisy in ("urllib3", "PIL", "google", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor."""
    return logging.getLogger(name)
