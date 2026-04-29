"""English → Bangla translation using deep-translator (Google Translate backend)."""
from __future__ import annotations

from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)


class Translator:
    """Wraps deep-translator with graceful fallback if offline."""

    def __init__(self, target: str = "bn"):
        self.target = target
        try:
            from deep_translator import GoogleTranslator
            self._engine_cls = GoogleTranslator
        except ImportError:
            log.warning("deep-translator not installed; translation disabled")
            self._engine_cls = None

    def translate(self, text: str, source: str = "auto") -> Optional[str]:
        """Translate text to target language. Returns None on failure."""
        if not text or not self._engine_cls:
            return None
        try:
            translated = self._engine_cls(source=source, target=self.target).translate(text)
            return translated
        except Exception as e:
            log.warning("Translation failed: %s", e)
            return None
