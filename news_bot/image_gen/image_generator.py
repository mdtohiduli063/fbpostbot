"""
1080×1080 news-card image generator with audience-attractive layout.

Layout (top → bottom)
─────────────────────
  ┌────────────────────────────────────────────┐
  │ ▰▰ 1-LINE HEADLINE (top ribbon, big bold) ▰│  ← always single line, top
  │  [category badge]                          │
  │                                            │
  │     summary body (3-7 lines, premium)      │
  │     auto-shrunk to fit the card            │
  │                                            │
  │     ─── divider ───                        │
  │     💬 engagement hook                     │
  │                                            │
  │  date • brand              source: <site>  │
  │            BOT BY TOHIDUL                  │
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
    "breaking":      ((220, 30, 50),   (140, 15, 25),  (45, 5, 10)),
    "politics":      ((25, 65, 150),   (15, 40, 100),  (5, 12, 40)),
    "cricket":       ((35, 145, 70),   (15, 95, 45),   (5, 40, 18)),
    "entertainment": ((170, 45, 155),  (105, 25, 115), (35, 5, 55)),
    "government":    ((50, 60, 120),   (30, 35, 75),   (12, 15, 35)),
    "price":         ((215, 145, 30),  (150, 85, 18),  (60, 30, 5)),
    "exam_jobs":     ((35, 140, 155),  (20, 90, 110),  (5, 40, 50)),
    "tech":          ((35, 115, 180),  (15, 65, 120),  (5, 20, 50)),
    "world":         ((105, 40, 175),  (60, 20, 120),  (20, 5, 55)),
    "sports":        ((30, 155, 100),  (15, 100, 65),  (5, 45, 25)),
    "general":       ((45, 50, 75),    (25, 30, 50),   (10, 12, 22)),
}

CATEGORY_ACCENT: Dict[str, RGB] = {
    "breaking":      (255, 230, 80),
    "politics":      (255, 215, 0),
    "cricket":       (255, 255, 255),
    "entertainment": (255, 230, 120),
    "government":    (220, 220, 255),
    "price":         (255, 235, 130),
    "exam_jobs":     (200, 255, 240),
    "tech":          (140, 220, 255),
    "world":         (255, 220, 240),
    "sports":        (255, 240, 130),
    "general":       (200, 210, 240),
}

CATEGORY_BADGE_BN: Dict[str, str] = {
    "breaking":      "ব্রেকিং নিউজ",
    "politics":      "রাজনীতি",
    "cricket":       "ক্রিকেট",
    "entertainment": "বিনোদন",
    "government":    "সরকার",
    "price":         "বাজার",
    "exam_jobs":     "চাকরি ও পরীক্ষা",
    "tech":          "প্রযুক্তি",
    "world":         "আন্তর্জাতিক",
    "sports":        "খেলা",
    "general":       "সংবাদ",
}

CATEGORY_EMOJI_BADGE: Dict[str, str] = {
    "breaking":      "🚨",
    "politics":      "🏛",
    "cricket":       "🏏",
    "entertainment": "🎬",
    "government":    "📜",
    "price":         "💰",
    "exam_jobs":     "🎓",
    "tech":          "💻",
    "world":         "🌍",
    "sports":        "🏆",
    "general":       "📰",
}


class ImageGenerator:
    """Render Bangla news cards with single-line top headline + premium look."""

    def __init__(self, cfg: Dict[str, Any], output_dir: str,
                 logo_path: Optional[str] = None):
        self.width   = int(cfg.get("width", 1080))
        self.height  = int(cfg.get("height", 1080))
        self.headline_size = int(cfg.get("headline_font_size", 64))
        self.body_size     = int(cfg.get("body_font_size", 40))
        self.footer_size   = int(cfg.get("footer_font_size", 30))
        self.credit_size   = int(cfg.get("credit_font_size", 26))
        self.padding       = int(cfg.get("padding", 60))
        self.brand_name    = cfg.get("brand_name", "News Summary")
        self.bot_credit    = cfg.get("bot_credit", "BOT BY TOHIDUL")
        self.text_color    = tuple(cfg.get("text_color", [255, 255, 255]))
        self.output_dir    = output_dir
        self.logo_path     = logo_path
        os.makedirs(self.output_dir, exist_ok=True)

        self.font_path = self._find_bangla_font()
        if not self.font_path:
            log.warning("No Bangla TTF found in assets/fonts/ — text quality will degrade.")

    # ───────────────────────────────────────── public ─────────────────────────────

    def generate(self, headline: str, body: str = "",
                 category: str = "general",
                 footer: Optional[str] = None,
                 source_name: Optional[str] = None,
                 engagement: Optional[str] = None) -> Optional[str]:
        """Render the news card. Headline always shown as a single line at top."""
        try:
            palette = CATEGORY_PALETTE.get(category, CATEGORY_PALETTE["general"])
            accent  = CATEGORY_ACCENT.get(category, CATEGORY_ACCENT["general"])

            # 1. Themed background (gradient + topic art + vignette)
            img = self._gradient_background(palette)
            self._draw_topic_art(img, category, accent)
            self._apply_vignette(img)

            draw = ImageDraw.Draw(img, "RGBA")

            # 2. Top headline ribbon — single line, big bold, always at the top
            ribbon_h = self._draw_top_headline_ribbon(
                draw, img, headline.strip() or "—",
                accent=accent, palette=palette, category=category,
            )

            # 3. Category badge (just under ribbon, left)
            # Note: Bangla font doesn't include color emoji glyphs, so we
            # avoid emoji on the image itself (caption keeps them).
            badge_text = CATEGORY_BADGE_BN.get(category, "সংবাদ")
            self._draw_badge(draw, badge_text,
                             x=self.padding, y=ribbon_h + 28, accent=accent)

            # 4. Body text block (centered between badge and footer)
            self._draw_body_block(draw, body or "",
                                  zone_top=ribbon_h + 130,
                                  zone_bot=self.height - 200,
                                  engagement=engagement)

            # 5. Two-row footer
            footer_main = footer or (
                datetime.now().strftime("%d %b %Y") + "  •  " + self.brand_name
            )
            self._draw_footer(draw, footer_main, self.bot_credit,
                              source_name=source_name)

            # 6. Bottom accent bar
            draw.rectangle(
                [0, self.height - 10, self.width, self.height], fill=palette[2],
            )

            # 7. Optional logo (top-right corner, below ribbon)
            self._paste_logo(img, top_offset=ribbon_h + 24)

            # 8. Save
            img = img.convert("RGB")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = os.path.join(self.output_dir, f"news_{category}_{ts}.jpg")
            img.save(out_path, "JPEG", quality=92, optimize=True)
            log.info("🖼  Image saved: %s", out_path)
            return out_path
        except Exception as e:
            log.exception("Image generation failed: %s", e)
            return None

    # ───────────────────────── background + decorations ─────────────────────────

    def _gradient_background(self, palette: Tuple[RGB, RGB, RGB]) -> Image.Image:
        top, mid, bot = palette
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255))
        px = img.load()
        h = self.height
        mid_y = h // 2
        for y in range(h):
            if y < mid_y:
                t = y / max(1, mid_y)
                r = int(top[0] + (mid[0] - top[0]) * t)
                g = int(top[1] + (mid[1] - top[1]) * t)
                b = int(top[2] + (mid[2] - top[2]) * t)
            else:
                t = (y - mid_y) / max(1, h - mid_y)
                r = int(mid[0] + (bot[0] - mid[0]) * t)
                g = int(mid[1] + (bot[1] - mid[1]) * t)
                b = int(mid[2] + (bot[2] - mid[2]) * t)
            for x in range(self.width):
                px[x, y] = (r, g, b, 255)
        return img

    def _apply_vignette(self, img: Image.Image) -> None:
        """Soft dark vignette to keep the centre readable."""
        vignette = Image.new("L", (self.width, self.height), 0)
        vd = ImageDraw.Draw(vignette)
        cx, cy = self.width // 2, self.height // 2
        max_r = int(math.hypot(cx, cy))
        for r in range(max_r, 0, -8):
            alpha = int(110 * (r / max_r) ** 2.2)
            vd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=alpha)
        vignette = vignette.filter(ImageFilter.GaussianBlur(radius=80))
        black = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255))
        img.paste(black, (0, 0), vignette)

    def _draw_topic_art(self, img: Image.Image, category: str, accent: RGB) -> None:
        """Soft, blurred topical decorations behind the text."""
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        soft1 = (*accent, 35)
        soft2 = (*accent, 22)

        if category == "breaking":
            for i in range(6):
                cx = random.randint(80, self.width - 80)
                cy = random.randint(self.height - 380, self.height - 120)
                self._draw_exclamation(draw, cx, cy, h=80, fill=soft1)
        elif category in ("cricket", "sports"):
            for i in range(40):
                cx = random.randint(0, self.width)
                cy = random.randint(self.height // 2, self.height - 60)
                draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=soft2)
        elif category == "tech":
            for i in range(0, self.width, 60):
                draw.line([(i, 0), (i, self.height)], fill=soft2, width=1)
            for j in range(0, self.height, 60):
                draw.line([(0, j), (self.width, j)], fill=soft2, width=1)
        elif category == "entertainment":
            for i in range(8):
                cx = random.randint(60, self.width - 60)
                cy = random.randint(self.height - 360, self.height - 120)
                self._draw_star(draw, cx, cy, r=42, fill=soft1)
        elif category == "world":
            for r in range(120, 600, 120):
                draw.ellipse(
                    [self.width - r, self.height - r,
                     self.width + r, self.height + r],
                    outline=soft1, width=3,
                )
        else:
            # Soft abstract waves for any other category
            for i in range(0, self.width + 200, 40):
                draw.arc([i - 200, self.height - 320, i + 200, self.height - 80],
                         start=0, end=180, fill=soft2, width=3)

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

    # ─────────────────────────── top headline ribbon ───────────────────────────

    def _draw_top_headline_ribbon(self, draw: ImageDraw.ImageDraw,
                                  img: Image.Image, headline: str,
                                  accent: RGB, palette: Tuple[RGB, RGB, RGB],
                                  category: str) -> int:
        """Top ribbon area with a single-line bold headline.

        Always renders the headline on ONE line — auto-shrinks the font until
        the text fits (down to a sensible minimum). Returns the height of the
        ribbon (so callers can place content below it)."""
        ribbon_h = 170
        # Ribbon background — dark translucent strip with accent borders
        ribbon = Image.new("RGBA", (self.width, ribbon_h), (0, 0, 0, 215))
        img.alpha_composite(ribbon, (0, 0))

        # Top + bottom accent strips
        draw.rectangle([0, 0, self.width, 8], fill=(*accent, 255))
        draw.rectangle([0, ribbon_h - 4, self.width, ribbon_h], fill=palette[0])

        # Single-line headline (auto-shrunk to fit horizontally)
        max_width = self.width - 2 * (self.padding - 10)
        size = self.headline_size
        min_size = 22  # shrink aggressively before truncating
        font = self._font(size)
        while size > min_size and self._text_width(headline, font) > max_width:
            size -= 2
            font = self._font(size)

        # If still too wide at min size, hard-truncate with ellipsis
        text = headline
        if self._text_width(text, font) > max_width:
            while text and self._text_width(text + "…", font) > max_width:
                text = text[:-1]
            text = (text.rstrip() + "…") if text else "…"

        # Center vertically inside ribbon
        try:
            l, t, r, b = font.getbbox(text)
            tw, th = r - l, b - t
        except Exception:
            tw, th = self._text_width(text, font), size
        x = (self.width - tw) // 2
        y = (ribbon_h - th) // 2 - 4

        # Strong shadow for premium look
        draw.text((x + 3, y + 3), text, fill=(0, 0, 0, 220), font=font)
        draw.text((x, y), text, fill=self.text_color, font=font)

        return ribbon_h

    # ─────────────────────────── badges + body ───────────────────────────

    def _draw_badge(self, draw: ImageDraw.ImageDraw, text: str,
                    x: int, y: int, accent: RGB) -> None:
        font = self._font(self.footer_size)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 18, self.footer_size
        pad_x, pad_y = 26, 12
        # accent left bar
        draw.rectangle([x, y, x + 8, y + th + pad_y * 2], fill=(*accent, 255))
        # white pill
        draw.rectangle(
            [x + 8, y, x + tw + pad_x * 2, y + th + pad_y * 2],
            fill=(255, 255, 255, 245),
        )
        draw.text((x + 8 + pad_x, y + pad_y), text, fill=(20, 20, 20), font=font)

    def _draw_body_block(self, draw: ImageDraw.ImageDraw, body: str,
                         zone_top: int, zone_bot: int,
                         engagement: Optional[str]) -> None:
        zone_h = zone_bot - zone_top
        body = (body or "").strip()
        if not body:
            return

        b_size, b_lines = self._fit_text(
            body, max_width=self.width - 2 * self.padding - 40,
            initial_size=self.body_size, min_size=24, max_lines=8,
        )
        b_font = self._font(b_size)
        b_line_h = int(b_size * 1.42)
        body_block_h = b_line_h * len(b_lines)

        eng_block_h = 0
        e_font = None
        if engagement:
            e_size, _ = self._fit_text(
                engagement, max_width=self.width - 2 * self.padding,
                initial_size=self.body_size - 4, min_size=22, max_lines=2,
            )
            e_font = self._font(e_size)
            eng_block_h = int(e_size * 1.4) + 30  # divider gap

        total = body_block_h + eng_block_h
        start_y = zone_top + max(0, (zone_h - total) // 2)

        # Body lines (centered)
        for i, ln in enumerate(b_lines):
            self._draw_centered(draw, ln, b_font,
                                y=start_y + i * b_line_h,
                                fill=(245, 245, 245), shadow=True,
                                shadow_offset=2)

        # Divider + engagement
        if engagement and e_font is not None:
            cy = start_y + body_block_h + 12
            cx = self.width // 2
            draw.rectangle([cx - 70, cy, cx + 70, cy + 3],
                           fill=(255, 255, 255, 180))
            # No emoji/special symbols here — Bangla font lacks those glyphs.
            self._draw_centered(draw, "» " + engagement, e_font,
                                y=cy + 18, fill=(255, 235, 160),
                                shadow=True, shadow_offset=2)

    def _draw_footer(self, draw: ImageDraw.ImageDraw,
                     line1: str, line2: str,
                     source_name: Optional[str] = None) -> None:
        f1 = self._font(self.footer_size)
        f2 = self._font(self.credit_size)
        f3 = self._font(self.credit_size)

        # bottom-most: credit line (yellow)
        y2 = self.height - 40 - self.credit_size
        self._draw_centered(draw, line2, f2, y=y2,
                            fill=(255, 230, 130), shadow=True, shadow_offset=2)

        # second from bottom: date • brand
        y1 = y2 - 14 - self.footer_size
        self._draw_centered(draw, line1, f1, y=y1,
                            fill=self.text_color, shadow=True, shadow_offset=2)

        # source line (small, top of footer) — no emoji on image
        if source_name:
            src_text = f"সূত্র: {source_name}"
            ys = y1 - 14 - self.credit_size
            self._draw_centered(draw, src_text, f3, y=ys,
                                fill=(220, 230, 255), shadow=True, shadow_offset=1)

    def _draw_centered(self, draw: ImageDraw.ImageDraw, text: str,
                       font: ImageFont.ImageFont, y: int, fill,
                       shadow: bool = False, shadow_offset: int = 3) -> None:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = self._text_width(text, font)
        x = (self.width - tw) // 2
        if shadow:
            draw.text((x + shadow_offset, y + shadow_offset), text,
                      fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), text, fill=fill, font=font)

    def _paste_logo(self, img: Image.Image, top_offset: int = 0) -> None:
        if not self.logo_path or not os.path.isfile(self.logo_path):
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            target_w = 110
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
            img.paste(logo,
                      (self.width - target_w - self.padding, top_offset),
                      logo)
        except Exception as e:
            log.warning("Logo paste failed: %s", e)

    # ───────────────────────────── text fitting ──────────────────────────

    def _fit_text(self, text: str, max_width: int,
                  initial_size: int, min_size: int,
                  max_lines: int) -> Tuple[int, List[str]]:
        size = initial_size
        while size >= min_size:
            font = self._font(size)
            lines = self._wrap_to_width(text, font, max_width)
            if len(lines) <= max_lines:
                return size, lines
            size -= 3
        font = self._font(min_size)
        lines = self._wrap_to_width(text, font, max_width)[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip() + "…"
        return min_size, lines

    def _wrap_to_width(self, text: str, font: ImageFont.ImageFont,
                       max_width: int) -> List[str]:
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

    # ───────────────────────────────── fonts ─────────────────────────────

    def _find_bangla_font(self) -> Optional[str]:
        # Resolve relative paths against the repo root + module dir
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for cand in BANGLA_FONT_CANDIDATES:
            for base in (cand, os.path.join(here, cand), os.path.abspath(cand)):
                if os.path.isfile(base):
                    return base
        return None

    def _font(self, size: int) -> ImageFont.ImageFont:
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size=size)
            except Exception:
                pass
        return ImageFont.load_default()
