"""
Generates 1080x1080 news-card image with Bangla headline + summary body
and topic-themed decorative background art.

Layout
------
  ┌────────────────────────────────────────────┐
  │ ▰▰▰ accent bar                             │
  │  [Category badge]                          │
  │                                            │
  │     BIG BOLD HEADLINE (centered)           │
  │     up to 4 lines, auto-shrunk to fit      │
  │  ─────────── divider ───────────           │
  │                                            │
  │     Summary body (3-7 lines)               │
  │     readable medium font                   │
  │                                            │
  │     28 Apr 2026 • News Summary             │
  │            BOT BY TOHIDUL                  │
  │ ▰▰▰ accent bar                             │
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

from ..utils.logger import get_logger

log = get_logger(__name__)

BANGLA_FONT_CANDIDATES = [
    "assets/fonts/NotoSansBengali-Bold.ttf",
    "assets/fonts/NotoSansBengali-Regular.ttf",
    "news_bot/assets/fonts/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansBengali-Bold.ttf",
]

RGB = Tuple[int, int, int]

# Rich 3-stop gradients per category. (top, middle, bottom)
CATEGORY_PALETTE: Dict[str, Tuple[RGB, RGB, RGB]] = {
    "breaking":      ((180, 20, 35),   (110, 10, 20),  (40, 5, 10)),
    "politics":      ((20, 55, 130),   (15, 35, 90),   (5, 12, 40)),
    "cricket":       ((30, 130, 60),   (15, 90, 40),   (5, 40, 18)),
    "entertainment": ((150, 40, 140),  (95, 25, 105),  (35, 5, 55)),
    "government":    ((45, 55, 110),   (30, 35, 75),   (12, 15, 35)),
    "price":         ((195, 130, 25),  (140, 80, 15),  (60, 30, 5)),
    "exam_jobs":     ((30, 125, 140),  (20, 85, 105),  (5, 40, 50)),
    "tech":          ((30, 105, 165),  (15, 60, 110),  (5, 20, 50)),
    "world":         ((95, 35, 160),   (55, 20, 110),  (20, 5, 55)),
    "sports":        ((25, 140, 90),   (15, 95, 60),   (5, 45, 25)),
    "general":       ((40, 45, 65),    (25, 30, 45),   (10, 12, 22)),
}

CATEGORY_ACCENT: Dict[str, RGB] = {
    "breaking": (255, 230, 80),
    "politics": (255, 215, 0),
    "cricket": (255, 255, 255),
    "entertainment": (255, 230, 120),
    "government": (220, 220, 255),
    "price": (255, 235, 130),
    "exam_jobs": (200, 255, 240),
    "tech": (140, 220, 255),
    "world": (255, 220, 240),
    "sports": (255, 240, 130),
    "general": (200, 210, 240),
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
    "sports": "খেলা",
    "general": "সংবাদ",
}


class ImageGenerator:
    """Render Bangla news cards with topic-themed background art."""

    def __init__(self, cfg: Dict[str, Any], output_dir: str,
                 logo_path: Optional[str] = None):
        self.width = int(cfg.get("width", 1080))
        self.height = int(cfg.get("height", 1080))
        self.headline_size = int(cfg.get("headline_font_size", 72))
        self.body_size = int(cfg.get("body_font_size", 38))
        self.footer_size = int(cfg.get("footer_font_size", 32))
        self.credit_size = int(cfg.get("credit_font_size", 26))
        self.padding = int(cfg.get("padding", 70))
        self.brand_name = cfg.get("brand_name", "News Summary")
        self.bot_credit = cfg.get("bot_credit", "BOT BY TOHIDUL")
        self.text_color = tuple(cfg.get("text_color", [255, 255, 255]))
        self.output_dir = output_dir
        self.logo_path = logo_path
        os.makedirs(self.output_dir, exist_ok=True)

        self.font_path = self._find_bangla_font()
        if not self.font_path:
            log.warning("No Bangla TTF found in assets/fonts/ — text quality will degrade.")

    # ───────────────────────────────────────── public ─────────────────────────────

    def generate(self, headline: str, body: str = "",
                 category: str = "general",
                 footer: Optional[str] = None) -> Optional[str]:
        """Render the news card. ``body`` is the multi-line summary text."""
        try:
            palette = CATEGORY_PALETTE.get(category, CATEGORY_PALETTE["general"])
            accent = CATEGORY_ACCENT.get(category, CATEGORY_ACCENT["general"])

            # 1. Themed background (gradient + topic art + vignette)
            img = self._gradient_background(palette)
            self._draw_topic_art(img, category, accent)
            self._apply_vignette(img)

            draw = ImageDraw.Draw(img, "RGBA")

            # 2. Top + bottom accent bars
            draw.rectangle([0, 0, self.width, 14], fill=palette[0])
            draw.rectangle([0, self.height - 14, self.width, self.height], fill=palette[2])

            # 3. Category badge (top-left)
            badge_text = CATEGORY_BADGE_BN.get(category, "সংবাদ")
            self._draw_badge(draw, badge_text, x=self.padding, y=50, accent=accent)

            # 4. Headline + body text block
            self._draw_text_block(draw, headline, body)

            # 5. Two-line footer: date • brand   /   BOT BY TOHIDUL
            footer_main = footer or (
                datetime.now().strftime("%d %b %Y") + "  •  " + self.brand_name
            )
            self._draw_footer(draw, footer_main, self.bot_credit)

            # 6. Optional logo
            self._paste_logo(img)

            filename = f"post_{int(datetime.now().timestamp())}.png"
            out_path = os.path.join(self.output_dir, filename)
            img.convert("RGB").save(out_path, "PNG", optimize=True)
            log.info("Generated image: %s", out_path)
            return out_path
        except Exception as e:
            log.exception("Image generation failed: %s", e)
            return None

    # ──────────────────────────────────────── fonts ───────────────────────────────

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

    # ─────────────────────────────── background + art ────────────────────────────

    def _gradient_background(self, palette: Tuple[RGB, RGB, RGB]) -> Image.Image:
        """3-stop vertical gradient (top → middle → bottom)."""
        top, mid, bottom = palette
        img = Image.new("RGBA", (self.width, self.height), top + (255,))
        draw = ImageDraw.Draw(img)
        half = self.height // 2
        for y in range(self.height):
            if y <= half:
                t = y / max(1, half)
                r = int(top[0] + (mid[0] - top[0]) * t)
                g = int(top[1] + (mid[1] - top[1]) * t)
                b = int(top[2] + (mid[2] - top[2]) * t)
            else:
                t = (y - half) / max(1, self.height - half)
                r = int(mid[0] + (bottom[0] - mid[0]) * t)
                g = int(mid[1] + (bottom[1] - mid[1]) * t)
                b = int(mid[2] + (bottom[2] - mid[2]) * t)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b, 255))
        return img

    def _apply_vignette(self, img: Image.Image) -> None:
        """Subtle dark corners → keeps text readable."""
        vignette = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(vignette)
        for i in range(0, 8):
            alpha = int(8 + i * 5)
            inset = i * 18
            draw.rectangle(
                [inset, inset, self.width - inset, self.height - inset],
                outline=(0, 0, 0, alpha), width=12,
            )
        img.alpha_composite(vignette)

    def _draw_topic_art(self, img: Image.Image, category: str, accent: RGB) -> None:
        """Draw subtle, decorative topic-related shapes onto the background."""
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        soft = (*accent, 38)        # very faint accent for shapes
        soft2 = (255, 255, 255, 22)  # white wash for highlights
        rng = random.Random(hash(category) & 0xFFFFFFFF)

        if category == "breaking":
            # Diagonal warning stripes top-right
            for k in range(-4, 18):
                x0 = k * 90
                draw.polygon(
                    [(x0, 0), (x0 + 45, 0),
                     (x0 + 45 - 200, 200), (x0 - 200, 200)],
                    fill=(255, 230, 80, 30),
                )
            # Big "!" silhouette bottom-right
            self._draw_exclamation(draw, self.width - 200, self.height - 320, 160, soft)

        elif category == "politics":
            # Star pattern + flag stripes
            for cx, cy, r in [(160, 200, 70), (self.width - 220, 180, 55),
                              (220, self.height - 320, 90), (self.width - 160, self.height - 260, 60)]:
                self._draw_star(draw, cx, cy, r, soft)
            for i in range(3):
                y = 60 + i * 14
                draw.rectangle([self.width - 380, y, self.width - 80, y + 4], fill=soft2)

        elif category == "cricket":
            # Cricket ball + bat silhouette + grass curves
            cx, cy = self.width - 200, self.height - 240
            draw.ellipse([cx - 90, cy - 90, cx + 90, cy + 90], outline=(255, 255, 255, 50), width=6)
            for k in range(-4, 5):
                draw.line([(cx - 90, cy + k * 20), (cx + 90, cy + k * 20)],
                          fill=(255, 255, 255, 28), width=2)
            # bat
            draw.line([(cx - 280, cy - 280), (cx - 100, cy - 100)],
                      fill=(255, 230, 180, 70), width=22)

        elif category == "entertainment":
            # Film reel circles + stars
            for cx, cy, r in [(180, 220, 110), (self.width - 200, self.height - 260, 130)]:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=soft, width=8)
                for ang in range(0, 360, 45):
                    px = cx + int(r * 0.55 * math.cos(math.radians(ang)))
                    py = cy + int(r * 0.55 * math.sin(math.radians(ang)))
                    draw.ellipse([px - 18, py - 18, px + 18, py + 18], fill=soft)
            for _ in range(6):
                self._draw_star(
                    draw, rng.randint(150, self.width - 150),
                    rng.randint(120, self.height - 120),
                    rng.randint(20, 36), soft2,
                )

        elif category == "government":
            # Greek-column rectangles
            base_y = self.height - 200
            for i in range(5):
                x = self.width - 480 + i * 90
                draw.rectangle([x, base_y - 280, x + 50, base_y], fill=soft)
            draw.rectangle([self.width - 510, base_y, self.width - 30, base_y + 22], fill=soft)
            draw.rectangle([self.width - 510, base_y - 300, self.width - 30, base_y - 280], fill=soft)

        elif category == "price":
            # Big faded ৳ symbol + bar chart silhouette
            big = self._font(520)
            draw.text((self.width - 460, self.height - 620), "৳",
                      fill=(*accent, 38), font=big)
            heights = [80, 130, 100, 170, 140, 200]
            for i, h in enumerate(heights):
                x = 80 + i * 50
                y = self.height - 220
                draw.rectangle([x, y - h, x + 36, y], fill=(*accent, 50))

        elif category == "exam_jobs":
            # Big "A+" + book lines
            big = self._font(420)
            draw.text((self.width - 430, -40), "A+", fill=(*accent, 36), font=big)
            for i in range(7):
                y = self.height - 280 + i * 22
                draw.line([(80, y), (380, y)], fill=soft2, width=3)
            draw.line([(80, self.height - 296), (380, self.height - 296)],
                      fill=soft, width=5)

        elif category == "tech":
            # Circuit grid + glowing nodes
            for x in range(0, self.width, 90):
                draw.line([(x, 0), (x, self.height)], fill=(255, 255, 255, 12), width=1)
            for y in range(0, self.height, 90):
                draw.line([(0, y), (self.width, y)], fill=(255, 255, 255, 12), width=1)
            for _ in range(14):
                cx = rng.randint(80, self.width - 80)
                cy = rng.randint(80, self.height - 80)
                draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10],
                             fill=(*accent, 110))
                draw.ellipse([cx - 22, cy - 22, cx + 22, cy + 22],
                             outline=(*accent, 60), width=2)

        elif category == "world":
            # Wireframe globe (concentric ellipses + meridians)
            cx, cy = self.width - 240, 260
            for r in (60, 110, 160, 210):
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=soft, width=2)
            for k in (60, 110, 160, 210):
                draw.ellipse([cx - 210, cy - k, cx + 210, cy + k], outline=soft, width=1)
            # dot scatter for "places"
            for _ in range(20):
                px = rng.randint(80, self.width - 80)
                py = rng.randint(120, self.height - 200)
                draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=soft2)

        elif category == "sports":
            # Trophy silhouette
            tx, ty = self.width - 260, self.height - 360
            draw.ellipse([tx - 100, ty, tx + 100, ty + 160], outline=soft, width=8)
            draw.rectangle([tx - 30, ty + 150, tx + 30, ty + 230], fill=soft)
            draw.rectangle([tx - 80, ty + 230, tx + 80, ty + 260], fill=soft)
            # Side handles
            draw.arc([tx - 160, ty + 10, tx - 80, ty + 130], start=270, end=90, fill=soft, width=8)
            draw.arc([tx + 80, ty + 10, tx + 160, ty + 130], start=90, end=270, fill=soft, width=8)
            for _ in range(5):
                self._draw_star(
                    draw, rng.randint(120, self.width - 120),
                    rng.randint(140, self.height - 320),
                    rng.randint(18, 32), soft2,
                )

        else:  # general
            # Soft abstract waves
            for i in range(0, self.width + 200, 40):
                draw.arc([i - 200, self.height - 320, i + 200, self.height - 80],
                         start=0, end=180, fill=soft2, width=3)

        # blur slightly so the art reads as background, not foreground noise
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=1.6))
        img.alpha_composite(overlay)

    @staticmethod
    def _draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                   r: int, fill) -> None:
        pts = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = r if i % 2 == 0 else r * 0.42
            pts.append((cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle)))
        draw.polygon(pts, fill=fill)

    @staticmethod
    def _draw_exclamation(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                          h: int, fill) -> None:
        w = int(h * 0.28)
        draw.rectangle([cx - w // 2, cy, cx + w // 2, cy + int(h * 0.7)], fill=fill)
        dot = int(h * 0.18)
        draw.ellipse(
            [cx - dot // 2, cy + int(h * 0.78),
             cx + dot // 2, cy + int(h * 0.78) + dot], fill=fill,
        )

    # ─────────────────────────────── text drawing ────────────────────────────────

    def _draw_badge(self, draw: ImageDraw.ImageDraw, text: str,
                    x: int, y: int, accent: RGB) -> None:
        font = self._font(self.footer_size)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 18, self.footer_size
        pad_x, pad_y = 26, 14
        # accent left bar
        draw.rectangle([x, y, x + 8, y + th + pad_y * 2], fill=(*accent, 255))
        # white pill
        draw.rectangle(
            [x + 8, y, x + tw + pad_x * 2, y + th + pad_y * 2],
            fill=(255, 255, 255, 245),
        )
        draw.text((x + 8 + pad_x, y + pad_y), text, fill=(20, 20, 20), font=font)

    def _draw_text_block(self, draw: ImageDraw.ImageDraw,
                         headline: str, body: str) -> None:
        """Render headline (top) + summary body (below) inside the central area."""
        # Layout zones (rough):
        #   y_top  = 175    (just below badge)
        #   y_bot  = 920    (just above footer)
        zone_top, zone_bot = 175, 920
        zone_h = zone_bot - zone_top

        # 1. Wrap + auto-shrink headline
        headline = headline.strip() or "—"
        h_size, h_lines = self._fit_text(
            headline, max_width=self.width - 2 * self.padding,
            initial_size=self.headline_size, min_size=44, max_lines=4,
        )
        h_font = self._font(h_size)

        # 2. Wrap + auto-shrink body
        body = (body or "").strip()
        if body:
            b_size, b_lines = self._fit_text(
                body, max_width=self.width - 2 * self.padding - 40,
                initial_size=self.body_size, min_size=24, max_lines=8,
            )
            b_font = self._font(b_size)
        else:
            b_lines, b_font, b_size = [], None, 0

        # Compute heights
        h_line_h = int(h_size * 1.30)
        b_line_h = int(b_size * 1.45) if b_size else 0
        head_block_h = h_line_h * len(h_lines)
        body_block_h = b_line_h * len(b_lines)
        divider_gap = 40 if b_lines else 0
        divider_h = 4 if b_lines else 0
        total = head_block_h + divider_gap + divider_h + divider_gap + body_block_h

        start_y = zone_top + max(0, (zone_h - total) // 2)

        # 3. Draw headline
        for i, ln in enumerate(h_lines):
            self._draw_centered(draw, ln, h_font,
                                y=start_y + i * h_line_h,
                                fill=self.text_color, shadow=True)
        cursor_y = start_y + head_block_h

        # 4. Divider line under headline
        if b_lines:
            cursor_y += divider_gap
            cx = self.width // 2
            draw.rectangle([cx - 90, cursor_y, cx + 90, cursor_y + divider_h],
                           fill=(255, 255, 255, 180))
            cursor_y += divider_h + divider_gap

            # 5. Body lines
            for i, ln in enumerate(b_lines):
                self._draw_centered(draw, ln, b_font,
                                    y=cursor_y + i * b_line_h,
                                    fill=(245, 245, 245), shadow=True,
                                    shadow_offset=2)

    def _draw_footer(self, draw: ImageDraw.ImageDraw,
                     line1: str, line2: str) -> None:
        """Two-line footer at the bottom of the image."""
        f1 = self._font(self.footer_size)
        f2 = self._font(self.credit_size)

        # line2 = credit, anchored above the bottom accent bar
        y2 = self.height - 30 - self.credit_size
        self._draw_centered(draw, line2, f2, y=y2,
                            fill=(255, 230, 130), shadow=True, shadow_offset=2)

        # line1 = "DD MMM YYYY • News Summary", just above line2
        y1 = y2 - 14 - self.footer_size
        self._draw_centered(draw, line1, f1, y=y1,
                            fill=self.text_color, shadow=True, shadow_offset=2)

    def _draw_centered(self, draw: ImageDraw.ImageDraw, text: str,
                       font: ImageFont.ImageFont, y: int, fill,
                       shadow: bool = False, shadow_offset: int = 3) -> None:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(text) * 18
        x = (self.width - tw) // 2
        if shadow:
            draw.text((x + shadow_offset, y + shadow_offset), text,
                      fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), text, fill=fill, font=font)

    def _paste_logo(self, img: Image.Image) -> None:
        if not self.logo_path or not os.path.isfile(self.logo_path):
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            target_w = 130
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
            img.paste(logo, (self.width - target_w - self.padding, self.padding), logo)
        except Exception as e:
            log.warning("Logo paste failed: %s", e)

    # ───────────────────────────── text fitting helpers ──────────────────────────

    def _fit_text(self, text: str, max_width: int,
                  initial_size: int, min_size: int,
                  max_lines: int) -> Tuple[int, List[str]]:
        """Shrink font and rewrap until text fits ``max_lines`` × ``max_width``."""
        size = initial_size
        while size >= min_size:
            font = self._font(size)
            lines = self._wrap_to_width(text, font, max_width)
            if len(lines) <= max_lines:
                return size, lines
            size -= 3
        # Final fallback: hard truncate
        font = self._font(min_size)
        lines = self._wrap_to_width(text, font, max_width)[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip() + "…"
        return min_size, lines

    def _wrap_to_width(self, text: str, font: ImageFont.ImageFont,
                       max_width: int) -> List[str]:
        """Greedy word-wrap that measures actual rendered width."""
        words = text.split()
        if not words:
            return []
        lines: List[str] = []
        current = words[0]
        for w in words[1:]:
            trial = f"{current} {w}"
            if self._text_width(trial, font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = w
        lines.append(current)
        return lines

    @staticmethod
    def _text_width(text: str, font: ImageFont.ImageFont) -> int:
        try:
            l, t, r, b = font.getbbox(text)
            return r - l
        except Exception:
            return len(text) * 18
