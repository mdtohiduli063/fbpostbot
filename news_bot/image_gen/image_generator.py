"""Generates 1080x1080 breaking-news style image with Bangla headline."""
from __future__ import annotations

import os
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from ..utils.logger import get_logger

log = get_logger(__name__)

# Search paths for a Bangla-capable TTF (must support \u0980-\u09FF).
# Patterns are matched with glob; keep them narrow to avoid scanning huge dirs.
BANGLA_FONT_CANDIDATES = [
    "assets/fonts/NotoSansBengali-Bold.ttf",
    "assets/fonts/NotoSansBengali-Regular.ttf",
    "news_bot/assets/fonts/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Bold.ttf",
]

CATEGORY_GRADIENTS: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {
    "breaking":      ((180, 10, 30),  (60, 0, 0)),
    "politics":      ((20, 60, 130),  (5, 15, 50)),
    "cricket":       ((20, 110, 50),  (5, 40, 20)),
    "entertainment": ((140, 30, 130), (45, 5, 60)),
    "government":    ((50, 50, 100),  (15, 15, 35)),
    "price":         ((180, 110, 20), (70, 35, 5)),
    "exam_jobs":     ((30, 110, 130), (5, 40, 50)),
    "tech":          ((30, 100, 150), (5, 20, 50)),
    "world":         ((90, 30, 150),  (25, 5, 60)),
    "sports":        ((20, 130, 80),  (5, 50, 25)),
    "general":       ((35, 35, 50),   (10, 10, 20)),
}


class ImageGenerator:
    """Renders Bangla-text post images suitable for Facebook (1080x1080)."""

    def __init__(self, cfg: Dict[str, Any], output_dir: str, logo_path: Optional[str] = None):
        self.width = int(cfg.get("width", 1080))
        self.height = int(cfg.get("height", 1080))
        self.headline_size = int(cfg.get("headline_font_size", 64))
        self.footer_size = int(cfg.get("footer_font_size", 32))
        self.padding = int(cfg.get("padding", 60))
        self.brand_name = cfg.get("brand_name", "AI News BD")
        self.text_color = tuple(cfg.get("text_color", [255, 255, 255]))
        self.output_dir = output_dir
        self.logo_path = logo_path
        os.makedirs(self.output_dir, exist_ok=True)

        self.font_path = self._find_bangla_font()
        if not self.font_path:
            log.warning(
                "No Bangla TTF found. Drop NotoSansBengali-Bold.ttf into assets/fonts/ "
                "for proper Bangla glyph rendering."
            )

    def generate(self, headline: str, category: str = "general",
                 footer: Optional[str] = None) -> Optional[str]:
        """Render image and return its path on disk."""
        try:
            top_color, bottom_color = CATEGORY_GRADIENTS.get(category, CATEGORY_GRADIENTS["general"])
            img = self._gradient_background(top_color, bottom_color)
            draw = ImageDraw.Draw(img)

            # Top accent bar
            draw.rectangle([0, 0, self.width, 14], fill=top_color)

            # Category badge
            badge_text = self._badge_text(category)
            self._draw_badge(draw, badge_text, x=self.padding, y=60)

            # Headline (wrapped, vertically centered)
            self._draw_headline(draw, headline)

            # Footer line
            footer_text = footer or datetime.now().strftime("%d %b %Y • ") + self.brand_name
            self._draw_footer(draw, footer_text)

            # Logo (optional)
            self._paste_logo(img)

            filename = f"post_{int(datetime.now().timestamp())}.png"
            out_path = os.path.join(self.output_dir, filename)
            img.save(out_path, "PNG", optimize=True)
            log.info("Generated image: %s", out_path)
            return out_path
        except Exception as e:
            log.exception("Image generation failed: %s", e)
            return None

    # ---------- internals ----------

    def _find_bangla_font(self) -> Optional[str]:
        import glob
        for pattern in BANGLA_FONT_CANDIDATES:
            for path in glob.glob(pattern):
                if os.path.isfile(path):
                    return path
        return None

    def _font(self, size: int) -> ImageFont.ImageFont:
        if self.font_path:
            try:
                # layout_engine=RAQM enables HarfBuzz for proper Bangla shaping
                # (conjuncts, vowel reordering). Falls back gracefully if unsupported.
                try:
                    return ImageFont.truetype(
                        self.font_path, size,
                        layout_engine=ImageFont.Layout.RAQM,
                    )
                except (AttributeError, OSError):
                    return ImageFont.truetype(self.font_path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    def _gradient_background(self, top: Tuple[int, int, int],
                             bottom: Tuple[int, int, int]) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), top)
        draw = ImageDraw.Draw(img)
        for y in range(self.height):
            ratio = y / self.height
            r = int(top[0] + (bottom[0] - top[0]) * ratio)
            g = int(top[1] + (bottom[1] - top[1]) * ratio)
            b = int(top[2] + (bottom[2] - top[2]) * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        return img

    @staticmethod
    def _badge_text(category: str) -> str:
        mapping = {
            "breaking": "ব্রেকিং নিউজ",
            "politics": "রাজনীতি",
            "cricket": "ক্রিকেট",
            "entertainment": "বিনোদন",
            "government": "সরকার",
            "price": "বাজার",
            "exam_jobs": "চাকরি ও পরীক্ষা",
            "tech": "প্রযুক্তি",
            "world": "আন্তর্জাতিক",
            "sports": "খেলা",
            "general": "সংবাদ",
        }
        return mapping.get(category, "সংবাদ")

    def _draw_badge(self, draw: ImageDraw.ImageDraw, text: str, x: int, y: int) -> None:
        font = self._font(self.footer_size)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 18, self.footer_size
        pad_x, pad_y = 24, 12
        draw.rectangle(
            [x, y, x + tw + pad_x * 2, y + th + pad_y * 2],
            fill=(255, 255, 255),
        )
        draw.text((x + pad_x, y + pad_y), text, fill=(20, 20, 20), font=font)

    def _draw_headline(self, draw: ImageDraw.ImageDraw, headline: str) -> None:
        font = self._font(self.headline_size)
        max_chars = self._estimate_max_chars(font)
        wrapped: List[str] = []
        for line in textwrap.wrap(headline, width=max_chars) or [headline]:
            wrapped.append(line)
            if len(wrapped) >= 6:
                break

        # Compute total height to vertically center
        line_heights = []
        for ln in wrapped:
            try:
                bbox = draw.textbbox((0, 0), ln, font=font)
                line_heights.append(bbox[3] - bbox[1] + 18)
            except Exception:
                line_heights.append(self.headline_size + 18)

        total_h = sum(line_heights)
        start_y = (self.height - total_h) // 2

        for i, ln in enumerate(wrapped):
            try:
                bbox = draw.textbbox((0, 0), ln, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(ln) * (self.headline_size // 2)
            x = (self.width - tw) // 2
            y = start_y + sum(line_heights[:i])
            # subtle shadow for readability
            draw.text((x + 3, y + 3), ln, fill=(0, 0, 0), font=font)
            draw.text((x, y), ln, fill=self.text_color, font=font)

    def _draw_footer(self, draw: ImageDraw.ImageDraw, text: str) -> None:
        font = self._font(self.footer_size)
        y = self.height - self.padding - self.footer_size
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(text) * 18
        x = (self.width - tw) // 2
        draw.text((x, y), text, fill=self.text_color, font=font)

    def _paste_logo(self, img: Image.Image) -> None:
        if not self.logo_path or not os.path.isfile(self.logo_path):
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            target_w = 140
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
            img.paste(logo, (self.width - target_w - self.padding, self.padding), logo)
        except Exception as e:
            log.warning("Logo paste failed: %s", e)

    @staticmethod
    def _estimate_max_chars(font: ImageFont.ImageFont) -> int:
        # Roughly 22 chars per line at 64pt on 1080 width works for Bangla
        try:
            size = font.size  # type: ignore[attr-defined]
        except AttributeError:
            size = 64
        return max(14, int(960 / max(20, size * 0.55)))
