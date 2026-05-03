"""
1080×1080 Bangla news-card image generator — professional TV news card style.

Layout (top → bottom)
─────────────────────
  ┌────────────────────────────────────────────┐
  │ ▌CATEGORY BADGE                            │  ← accent-colored pill, 68px from top
  │                                            │
  │   HEADLINE TEXT (large, up to 3 lines)     │  ← bold, white, left-aligned
  │   (auto-wraps before shrinking)            │
  │                                            │
  │─────────── accent divider ─────────────────│
  │                                            │
  │   Body summary text, wrapped, uniform      │  ← clean readable body
  │   ...                                      │
  │                                            │
  │████████████████████████████████████████████│  ← bottom brand bar
  └────────────────────────────────────────────┘
"""

from __future__ import annotations

import math
import os
import random
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.logger import get_logger
from .bangla_renderer import BanglaTextRenderer, get_renderer

log = get_logger(__name__)

BANGLA_FONT_CANDIDATES = [
    "assets/fonts/NotoSansBengali-Bold.ttf",
    "assets/fonts/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Bold.ttf",
]

RGB = Tuple[int, int, int]

# ─── Palette: (bg_dark, bg_mid, bg_light, accent, headline_text, body_text) ──
# Each category: dark BG top, lighter BG bottom, accent strip color
CATEGORY_PALETTE: Dict[str, Tuple[RGB, RGB, RGB]] = {
    "breaking": ((18, 8, 8), (45, 10, 12), (90, 18, 22)),
    "politics": ((6, 14, 38), (12, 28, 70), (22, 45, 110)),
    "cricket": ((5, 28, 14), (10, 55, 28), (18, 90, 48)),
    "entertainment": ((28, 8, 38), (55, 15, 72), (100, 28, 130)),
    "government": ((10, 14, 32), (20, 28, 58), (38, 50, 100)),
    "price": ((30, 20, 4), (65, 42, 8), (120, 78, 14)),
    "exam_jobs": ((5, 28, 32), (10, 55, 65), (18, 95, 110)),
    "tech": ((5, 18, 38), (10, 35, 72), (18, 60, 130)),
    "world": ((22, 8, 38), (42, 15, 72), (78, 28, 130)),
    "sports": ((5, 28, 20), (10, 55, 40), (18, 100, 72)),
    "general": ((12, 14, 22), (20, 24, 40), (35, 40, 68)),
}

CATEGORY_ACCENT: Dict[str, RGB] = {
    "breaking": (235, 55, 55),
    "politics": (50, 130, 255),
    "cricket": (50, 200, 100),
    "entertainment": (210, 80, 220),
    "government": (80, 120, 240),
    "price": (240, 165, 40),
    "exam_jobs": (40, 200, 200),
    "tech": (60, 165, 255),
    "world": (160, 80, 255),
    "sports": (50, 210, 130),
    "general": (100, 140, 220),
}

CATEGORY_BADGE_BN: Dict[str, str] = {
    "breaking": "ব্রেকিং নিউজ",
    "politics": "রাজনীতি",
    "cricket": "ক্রিকেট",
    "entertainment": "বিনোদন",
    "government": "সরকার",
    "price": "বাজার",
    "exam_jobs": "চাকরি ও পরীক্ষা",
    "tech": "প্রযুক্তি",
    "world": "আন্তর্জাতিক",
    "sports": "খেলাধুলা",
    "general": "সংবাদ",
}


class ImageGenerator:
    """Render Bangla news cards — professional TV news card style."""

    def __init__(
        self, cfg: Dict[str, Any], output_dir: str, logo_path: Optional[str] = None
    ):
        self.width = int(cfg.get("width", 1080))
        self.height = int(cfg.get("height", 1080))
        self.headline_size = int(cfg.get("headline_font_size", 62))
        self.body_size = int(cfg.get("body_font_size", 38))
        self.badge_size = int(cfg.get("footer_font_size", 28))
        self.credit_size = int(cfg.get("credit_font_size", 24))
        self.padding = int(cfg.get("padding", 58))
        self.brand_name = cfg.get("brand_name", "News Summary")
        self.output_dir = output_dir
        self.logo_path = logo_path
        os.makedirs(self.output_dir, exist_ok=True)

        self.font_path = self._find_bangla_font()
        if not self.font_path:
            log.warning("No Bangla TTF found — text quality will degrade.")
            self._renderer: Optional[BanglaTextRenderer] = None
        else:
            self._renderer = get_renderer(self.font_path)

    # ─────────────────────────────── public API ──────────────────────────────

    def generate(
        self,
        headline: str,
        body: str = "",
        category: str = "general",
        footer: Optional[str] = None,
        source_name: Optional[str] = None,
        engagement: Optional[str] = None,
    ) -> Optional[str]:
        try:
            palette = CATEGORY_PALETTE.get(category, CATEGORY_PALETTE["general"])
            accent = CATEGORY_ACCENT.get(category, CATEGORY_ACCENT["general"])

            # 1. Background
            img = self._make_background(palette, accent)

            draw = ImageDraw.Draw(img, "RGBA")

            # Layout constants
            pad = self.padding
            content_w = self.width - 2 * pad

            # 2. Top accent strip
            draw.rectangle([0, 0, self.width, 6], fill=(*accent, 255))

            # 3. Category badge (pill) — top-left
            badge_text = CATEGORY_BADGE_BN.get(category, "সংবাদ")
            badge_bot = self._draw_badge(
                draw, img, badge_text, x=pad, y=38, accent=accent
            )

            # 4. Headline block — large, wrapped, left-aligned
            hl_top = badge_bot + 22
            headline_bot = self._draw_headline(
                img, headline.strip() or "—", x=pad, top=hl_top, max_w=content_w
            )

            # 5. Accent divider line
            divider_y = headline_bot + 28
            self._draw_divider(draw, accent, y=divider_y)

            # 6. Body block — clean, uniform color
            body_top = divider_y + 12
            body_bot = self.height - 82  # leave room for bottom bar
            self._draw_body(
                img, body or "", top=body_top, bot=body_bot, max_w=content_w
            )

            # 7. Bottom brand bar
            self._draw_bottom_bar(draw, img, accent, palette, source_name=source_name)

            # 8. Subtle outer border
            draw.rounded_rectangle(
                [8, 8, self.width - 8, self.height - 8],
                radius=12,
                outline=(*accent, 160),
                width=3,
            )

            # 9. Logo (optional, top-right)
            self._paste_logo(img, top_offset=38)

            # 10. Save
            img = img.convert("RGB")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = os.path.join(self.output_dir, f"news_{category}_{ts}.jpg")
            img.save(out_path, "JPEG", quality=93, optimize=True)
            log.info("🖼  Image saved: %s", out_path)
            return out_path

        except Exception as e:
            log.exception("Image generation failed: %s", e)
            return None

    # ─────────────────────────── background ─────────────────────────────────

    def _make_background(
        self, palette: Tuple[RGB, RGB, RGB], accent: RGB
    ) -> Image.Image:
        """Deep gradient background with subtle texture."""
        dark, mid, light = palette
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255))
        px = img.load()

        # Two-stop gradient (dark top → slightly lighter bottom)
        for y in range(self.height):
            t = y / (self.height - 1)
            # Ease-in-out
            t = t * t * (3 - 2 * t)
            r = int(dark[0] + (mid[0] - dark[0]) * t)
            g = int(dark[1] + (mid[1] - dark[1]) * t)
            b = int(dark[2] + (mid[2] - dark[2]) * t)
            for x in range(self.width):
                px[x, y] = (r, g, b, 255)

        # Subtle accent glow in top-left corner
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay, "RGBA")
        od.ellipse([-120, -120, 500, 500], fill=(*accent, 18))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=80))
        img.alpha_composite(overlay)

        # Subtle noise texture overlay
        overlay2 = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        od2 = ImageDraw.Draw(overlay2, "RGBA")
        # Faint grid lines for depth
        for y in range(0, self.height, 80):
            od2.line([(0, y), (self.width, y)], fill=(255, 255, 255, 6), width=1)
        img.alpha_composite(overlay2)

        return img

    # ─────────────────────────── badge ──────────────────────────────────────

    def _draw_badge(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        text: str,
        x: int,
        y: int,
        accent: RGB,
    ) -> int:
        """Draw a pill-shaped category badge. Returns the bottom y of the badge."""
        size = self.badge_size
        tw = self._bn_width(text, size)
        pad_x, pad_y = 20, 10
        pill_w = tw + pad_x * 2
        pill_h = size + pad_y * 2

        # Pill fill — accent color with slight transparency
        draw.rounded_rectangle(
            [x, y, x + pill_w, y + pill_h],
            radius=pill_h // 2,
            fill=(*accent, 230),
        )
        # Pill inner highlight
        draw.rounded_rectangle(
            [x + 2, y + 2, x + pill_w - 2, y + pill_h // 2 + 2],
            radius=(pill_h // 2) - 2,
            fill=(255, 255, 255, 28),
        )

        # Badge text — dark/white depending on accent brightness
        brightness = (accent[0] * 299 + accent[1] * 587 + accent[2] * 114) // 1000
        text_fill = (15, 15, 15) if brightness > 130 else (255, 255, 255)
        self._bn_render(
            img, text, x + pad_x, y + pad_y, size, fill=text_fill, shadow=False
        )

        return y + pill_h

    # ─────────────────────────── headline ───────────────────────────────────

    def _draw_headline(
        self, img: Image.Image, text: str, x: int, top: int, max_w: int
    ) -> int:
        """Draw the headline, wrapping first before shrinking font.
        Returns the bottom y of the rendered headline block."""
        # Try sizes from large down; prefer wrapping to 3 lines over tiny font
        for size in range(self.headline_size, 30, -2):
            lines = self._wrap_to_width(text, size, max_w)
            if len(lines) <= 3:
                break

        line_h = int(size * 1.38)
        for i, ln in enumerate(lines):
            y = top + i * line_h
            # Stronger shadow for headline readability
            self._bn_render(
                img,
                ln,
                x=x,
                y=y,
                size=size,
                fill=(255, 255, 255),
                shadow=True,
                shadow_offset=3,
            )

        return top + len(lines) * line_h

    # ─────────────────────────── divider ────────────────────────────────────

    def _draw_divider(self, draw: ImageDraw.ImageDraw, accent: RGB, y: int) -> None:
        """Horizontal accent divider line with fade-out ends."""
        pad = self.padding
        # Main line
        draw.line([(pad, y), (self.width - pad, y)], fill=(*accent, 200), width=2)
        # Subtle glow above
        draw.line(
            [(pad, y - 1), (self.width - pad, y - 1)], fill=(*accent, 60), width=1
        )

    # ─────────────────────────── body ───────────────────────────────────────

    def _draw_body(
        self, img: Image.Image, body: str, top: int, bot: int, max_w: int
    ) -> None:
        """Render body summary with clean uniform text."""
        body = body.strip()
        if not body:
            return

        zone_h = bot - top
        # Remove emoji prefix if present (they don't render in Bangla font)
        import re

        body = re.sub(
            r"^[\U00010000-\U0010ffff\U00002600-\U000027BF\U0001F300-\U0001FAFF]\s*",
            "",
            body,
        )
        body = re.sub(
            r"^\W+\s*\w+[：:]\s*", "", body
        )  # remove "💰 দাম-দর সংক্রান্ত খবর:" prefix style

        max_lines = max(4, int(zone_h / (self.body_size * 1.52)))
        max_lines = min(10, max_lines)

        # Fit text
        size = self.body_size
        while size >= 24:
            lines = self._wrap_to_width(body, size, max_w)
            if len(lines) <= max_lines:
                break
            size -= 2

        lines = self._wrap_to_width(body, size, max_w)[:max_lines]
        if len(lines) == max_lines:
            last = lines[-1].rstrip()
            if self._bn_width(last + "…", size) <= max_w:
                lines[-1] = last + "…"

        line_h = int(size * 1.55)
        total_h = len(lines) * line_h

        # Vertically center body in its zone
        start_y = top + max(0, (zone_h - total_h) // 3)

        # Subtle semi-transparent body background panel
        pad = self.padding
        body_rect_top = start_y - 18
        body_rect_bot = start_y + total_h + 18
        panel = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel, "RGBA")
        pd.rounded_rectangle(
            [pad - 18, body_rect_top, self.width - pad + 18, body_rect_bot],
            radius=16,
            fill=(255, 255, 255, 14),
        )
        img.alpha_composite(panel)

        # Render each line — uniform soft white color
        for i, ln in enumerate(lines):
            y = start_y + i * line_h
            self._bn_render_centered(
                img,
                ln,
                y=y,
                size=size,
                fill=(232, 236, 245),
                shadow=True,
                shadow_offset=2,
            )

    # ─────────────────────────── bottom bar ─────────────────────────────────

    def _draw_bottom_bar(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        accent: RGB,
        palette: Tuple[RGB, RGB, RGB],
        source_name: Optional[str] = None,
    ) -> None:
        """Bottom brand bar with brand name centered."""
        bar_top = self.height - 78
        bar_h = 78

        # Bar background — slightly darker than page bg
        bar = Image.new("RGBA", (self.width, bar_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar, "RGBA")
        bd.rectangle([0, 0, self.width, bar_h], fill=(0, 0, 0, 140))
        img.alpha_composite(bar, (0, bar_top))

        # Top edge of bar — accent line
        draw.rectangle([0, bar_top, self.width, bar_top + 3], fill=(*accent, 210))

        # Brand name centered
        brand = self.brand_name.upper()
        brand_size = self.credit_size + 2
        bw = self._bn_width(brand, brand_size)
        bx = (self.width - bw) // 2
        by = bar_top + (bar_h - brand_size) // 2

        self._bn_render(
            img, brand, x=bx, y=by, size=brand_size, fill=(220, 225, 240), shadow=False
        )

        # Small accent dots flanking brand name
        dot_y = by + brand_size // 2
        dot_r = 4
        if bx > 40:
            draw.ellipse(
                [bx - 28 - dot_r, dot_y - dot_r, bx - 28 + dot_r, dot_y + dot_r],
                fill=(*accent, 200),
            )
            draw.ellipse(
                [
                    bx + bw + 24 - dot_r,
                    dot_y - dot_r,
                    bx + bw + 24 + dot_r,
                    dot_y + dot_r,
                ],
                fill=(*accent, 200),
            )

        owner = "BOT OWNER TOHIDUL"
        owner_size = self.credit_size
        ow = self._bn_width(owner, owner_size)
        ox = (self.width - ow) // 2
        oy = bar_top - owner_size - 10
        self._bn_render(
            img,
            owner,
            x=ox,
            y=oy,
            size=owner_size,
            fill=(255, 255, 255),
            shadow=True,
            shadow_offset=1,
        )

    # ─────────────────────────── logo ───────────────────────────────────────

    def _paste_logo(self, img: Image.Image, top_offset: int = 38) -> None:
        if not self.logo_path or not os.path.isfile(self.logo_path):
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            target_w = 100
            ratio = target_w / logo.width
            logo = logo.resize(
                (target_w, int(logo.height * ratio)), Image.Resampling.LANCZOS
            )
            img.paste(logo, (self.width - target_w - self.padding, top_offset), logo)
        except Exception as e:
            log.warning("Logo paste failed: %s", e)

    # ─────────────────────────── text helpers ───────────────────────────────

    def _wrap_to_width(self, text: str, size: int, max_width: int) -> List[str]:
        words = text.split()
        if not words:
            return []
        lines: List[str] = []
        current = words[0]
        for w in words[1:]:
            trial = f"{current} {w}"
            if self._bn_width(trial, size) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = w
        lines.append(current)
        return lines

    def _bn_width(self, text: str, size: int) -> int:
        if self._renderer:
            return self._renderer.text_width(text, size)
        return self._text_width(text, self._font(size))

    def _bn_render(
        self,
        img: Image.Image,
        text: str,
        x: int,
        y: int,
        size: int,
        fill: RGB,
        shadow: bool = False,
        shadow_offset: int = 2,
    ) -> int:
        if self._renderer:
            return self._renderer.render(
                img,
                text,
                x=x,
                y=y,
                size_px=size,
                fill=fill,
                shadow=shadow,
                shadow_offset=shadow_offset,
                shadow_fill=(0, 0, 0),
                shadow_alpha=190,
            )
        d = ImageDraw.Draw(img, "RGBA")
        font = self._font(size)
        if shadow:
            d.text(
                (x + shadow_offset, y + shadow_offset),
                text,
                fill=(0, 0, 0, 190),
                font=font,
            )
        d.text((x, y), text, fill=fill, font=font)
        try:
            l, t, r, b = font.getbbox(text)
            return r - l
        except Exception:
            return len(text) * size // 2

    def _bn_render_centered(
        self,
        img: Image.Image,
        text: str,
        y: int,
        size: int,
        fill: RGB,
        shadow: bool = False,
        shadow_offset: int = 2,
    ) -> None:
        tw = self._bn_width(text, size)
        x = (self.width - tw) // 2
        self._bn_render(
            img, text, x, y, size, fill, shadow=shadow, shadow_offset=shadow_offset
        )

    @staticmethod
    def _text_width(text: str, font: ImageFont.ImageFont) -> int:
        try:
            l, t, r, b = font.getbbox(text)
            return r - l
        except Exception:
            return len(text) * 18

    # ─────────────────────────── fonts ──────────────────────────────────────

    def _find_bangla_font(self, prefer_regular: bool = False) -> Optional[str]:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = list(BANGLA_FONT_CANDIDATES)
        if prefer_regular:
            candidates.sort(key=lambda p: ("Regular" not in p, p))
        for cand in candidates:
            for base in (cand, os.path.join(here, cand), os.path.abspath(cand)):
                if os.path.isfile(base):
                    return base
        return None

    def _font(self, size: int):
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size=size)
            except Exception:
                pass
        return ImageFont.load_default()
