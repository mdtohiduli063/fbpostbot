"""
1080×1080 news-card image generator — clean, headline + summary only.

Layout (top → bottom)
─────────────────────
  ┌────────────────────────────────────────────┐
  │ ▰▰ 1-LINE HEADLINE (top ribbon, big bold) ▰│
  │  [category badge]                          │
  │                                            │
  │     detailed summary body                  │
  │     (auto-shrunk to fit, up to ~10 lines)  │
  │                                            │
  └────────────────────────────────────────────┘

Everything below the body has been intentionally removed: no divider,
no engagement hook, no date / brand line, no source line, no bot
credit — the image stays clean for the video pipeline that wraps it.
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

FONT_STYLES: Dict[str, Tuple[str, str]] = {
    "headline": ("normal", "bold"),
    "body": ("normal", "regular"),
    "badge": ("normal", "bold"),
    "accent": ("normal", "bold"),
    "credit": ("normal", "regular"),
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
        self.font_regular_path = self._find_bangla_font(prefer_regular=True)
        self.font_alt_path = self._find_alt_font()
        if not self.font_path:
            log.warning("No Bangla TTF found in assets/fonts/ — text quality will degrade.")
            self._renderer: Optional[BanglaTextRenderer] = None
        else:
            self._renderer = get_renderer(self.font_path)

    # ───────────────────────────────────────── public ─────────────────────────────

    def generate(self, headline: str, body: str = "",
                 category: str = "general",
                 footer: Optional[str] = None,         # kept for back-compat (ignored)
                 source_name: Optional[str] = None,    # kept for back-compat (ignored)
                 engagement: Optional[str] = None      # kept for back-compat (ignored)
                 ) -> Optional[str]:
        """Render the news card. Headline single-line on top + body fills the rest.

        ``footer`` / ``source_name`` / ``engagement`` are accepted for
        backwards compatibility but no longer drawn — the new clean layout
        is just headline + body (everything that used to be below the
        divider has been removed).
        """
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
            self._draw_badge(draw, img, badge_text,
                             x=self.padding, y=ribbon_h + 28, accent=accent)

            # 4. Body text — uses the entire space below the badge to ~36px
            # from the bottom edge. No divider, no footer, no credit line.
            self._draw_body_block(draw, img, body or "",
                                  zone_top=ribbon_h + 130,
                                  zone_bot=self.height - 60)

            # 5. Bottom accent bar (decorative — not text)
            draw.rectangle(
                [0, self.height - 10, self.width, self.height], fill=palette[2],
            )

            # 6. Optional logo (top-right corner, below ribbon)
            self._paste_logo(img, top_offset=ribbon_h + 24)

            # 7. Save
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
                img.putpixel((x, y), (r, g, b, 255))
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
        self._draw_frame_effects(img, accent, category)

    def _draw_frame_effects(self, img: Image.Image, accent: RGB, category: str) -> None:
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        border = (*accent, 120)
        inner = (255, 255, 255, 40)
        glow = (*accent, 55)

        for i in range(3):
            inset = 18 + i * 12
            draw.rounded_rectangle(
                [inset, inset, self.width - inset, self.height - inset],
                radius=max(16, 34 - i * 4),
                outline=border if i == 0 else inner,
                width=6 if i == 0 else 2,
            )
        draw.rounded_rectangle(
            [44, 44, self.width - 44, self.height - 44],
            radius=22,
            outline=glow,
            width=1,
        )
        for y in range(170, self.height - 120, 140):
            draw.line([(42, y), (self.width - 42, y)], fill=(255, 255, 255, 18), width=1)
        for i in range(10):
            x1 = 26 + i * 100
            x2 = min(x1 + 34, self.width - 26)
            y1 = self.height - 24
            draw.line([(x1, y1), (x2, y1)], fill=border, width=3)
        if category in ("breaking", "tech", "sports"):
            for x in range(80, self.width - 80, 120):
                draw.line([(x, 0), (x + 50, 50)], fill=glow, width=2)
                draw.line([(x, self.height), (x + 50, self.height - 50)], fill=glow, width=2)
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
        while size > min_size and self._bn_width(headline, size) > max_width:
            size -= 2

        # If still too wide at min size, hard-truncate with ellipsis
        text = headline
        if self._bn_width(text, size) > max_width:
            while text and self._bn_width(text + "…", size) > max_width:
                text = text[:-1]
            text = (text.rstrip() + "…") if text else "…"

        # Center horizontally + vertically inside ribbon
        tw = self._bn_width(text, size)
        th = size
        x = (self.width - tw) // 2
        y = (ribbon_h - th) // 2 - 4

        # Strong shadow for premium look
        self._bn_render(img, text, x, y, size, fill=self.text_color,
                        shadow=True, shadow_offset=3)

        return ribbon_h

    # ─────────────────────────── badges + body ───────────────────────────

    def _draw_badge(self, draw: ImageDraw.ImageDraw, img: Image.Image,
                    text: str, x: int, y: int, accent: RGB) -> None:
        size = self.footer_size
        tw = self._bn_width(text, size)
        th = size
        pad_x, pad_y = 26, 12
        # accent left bar
        draw.rectangle([x, y, x + 8, y + th + pad_y * 2], fill=(*accent, 255))
        # white pill
        draw.rectangle(
            [x + 8, y, x + tw + pad_x * 2, y + th + pad_y * 2],
            fill=(255, 255, 255, 245),
        )
        self._bn_render(img, text, x + 8 + pad_x, y + pad_y, size,
                        fill=(20, 20, 20))
        self._draw_accent_label(img, f"● {text}", x + tw + 28, y + 6, accent)

    def _draw_body_block(self, draw: ImageDraw.ImageDraw, img: Image.Image,
                         body: str, zone_top: int, zone_bot: int) -> None:
        """Render the summary body. Uses the entire vertical zone — no
        divider, no engagement hook, no footer below.
        """
        zone_h = zone_bot - zone_top
        body = (body or "").strip()
        if not body or zone_h < 80:
            return

        # How many lines can plausibly fit at this body size?
        # Body line-height factor is 1.42; reserve a little breathing room.
        # Allow up to 12 lines so longer summaries can fit the new clean
        # layout without truncation.
        max_lines_by_zone = max(4, int(zone_h / (self.body_size * 1.42)))
        max_lines = min(12, max_lines_by_zone)

        b_size, b_lines = self._fit_text(
            body, max_width=self.width - 2 * self.padding - 40,
            initial_size=self.body_size, min_size=22, max_lines=max_lines,
        )
        b_line_h = int(b_size * 1.42)
        body_block_h = b_line_h * len(b_lines)

        # Top-align with a small offset for breathing room — looks better
        # than vertical centering when the body is long.
        start_y = zone_top + max(0, (zone_h - body_block_h) // 4)

        for i, ln in enumerate(b_lines):
            color = self._body_line_color(i, len(b_lines))
            self._bn_render_centered(img, ln, y=start_y + i * b_line_h,
                                     size=b_size, fill=color,
                                     shadow=True, shadow_offset=2)
            self._draw_line_highlight(draw, start_y + i * b_line_h, color)

    def _draw_footer(self, draw: ImageDraw.ImageDraw, img: Image.Image,
                     line1: str, line2: str,
                     source_name: Optional[str] = None) -> None:
        # bottom-most: credit line (yellow)
        y2 = self.height - 40 - self.credit_size
        self._bn_render_centered(img, line2, y=y2, size=self.credit_size,
                                 fill=(255, 230, 130), shadow=True,
                                 shadow_offset=2)

        # second from bottom: date • brand
        y1 = y2 - 14 - self.footer_size
        self._bn_render_centered(img, line1, y=y1, size=self.footer_size,
                                 fill=self.text_color, shadow=True,
                                 shadow_offset=2)

        # source line (small, top of footer) — no emoji on image
        if source_name:
            src_text = f"সূত্র: {source_name}"
            ys = y1 - 14 - self.credit_size
            self._bn_render_centered(img, src_text, y=ys, size=self.credit_size,
                                     fill=(220, 230, 255), shadow=True,
                                     shadow_offset=1)

    def _paste_logo(self, img: Image.Image, top_offset: int = 0) -> None:
        if not self.logo_path or not os.path.isfile(self.logo_path):
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            target_w = 110
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)), Image.Resampling.LANCZOS)
            img.paste(logo,
                      (self.width - target_w - self.padding, top_offset),
                      logo)
        except Exception as e:
            log.warning("Logo paste failed: %s", e)

    def _draw_accent_label(self, img: Image.Image, text: str, x: int, y: int,
                           accent: RGB) -> None:
        size = max(18, self.credit_size - 4)
        self._bn_render(img, text, x, y, size, fill=accent, shadow=True, shadow_offset=1)

    def _body_line_color(self, index: int, total: int) -> RGB:
        if total <= 1:
            return (248, 248, 248)
        if index == 0:
            return (255, 245, 180)
        if index == total - 1:
            return (220, 235, 255)
        return (242, 242, 242)

    def _draw_line_highlight(self, draw: ImageDraw.ImageDraw, y: int,
                              color: RGB) -> None:
        draw.line(
            [(self.padding, y - 4), (self.width - self.padding, y - 4)],
            fill=(color[0], color[1], color[2], 36),
            width=1,
        )

    # ───────────────────────────── text fitting ──────────────────────────

    def _fit_text(self, text: str, max_width: int,
                  initial_size: int, min_size: int,
                  max_lines: int) -> Tuple[int, List[str]]:
        size = initial_size
        while size >= min_size:
            lines = self._wrap_to_width(text, size, max_width)
            if len(lines) <= max_lines:
                return size, lines
            size -= 3
        lines = self._wrap_to_width(text, min_size, max_width)[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip() + "…"
        return min_size, lines

    def _wrap_to_width(self, text: str, size: int,
                       max_width: int) -> List[str]:
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

    @staticmethod
    def _text_width(text: str, font: ImageFont.ImageFont) -> int:
        try:
            l, t, r, b = font.getbbox(text)
            return r - l
        except Exception:
            return len(text) * 18

    # ─────────────── Bangla shaping helpers (HarfBuzz + FreeType) ───────────

    def _bn_width(self, text: str, size: int) -> int:
        """Pixel width of `text` rendered at `size` with proper Bangla shaping."""
        if self._renderer:
            return self._renderer.text_width(text, size)
        return self._text_width(text, self._font(size))

    def _bn_render(self, img: Image.Image, text: str, x: int, y: int,
                   size: int, fill: RGB,
                   shadow: bool = False, shadow_offset: int = 2) -> int:
        """Render `text` at (x, y) (top-left) with proper Bangla shaping.

        Returns the advance width of the rendered text.
        """
        if self._renderer:
            return self._renderer.render(
                img, text, x=x, y=y, size_px=size, fill=fill,
                shadow=shadow, shadow_offset=shadow_offset,
                shadow_fill=(0, 0, 0), shadow_alpha=200,
            )
        # Fallback to PIL (English-only safe)
        d = ImageDraw.Draw(img, "RGBA")
        font = self._font(size)
        if shadow:
            d.text((x + shadow_offset, y + shadow_offset), text,
                   fill=(0, 0, 0, 200), font=font)
        d.text((x, y), text, fill=fill, font=font)
        try:
            l, t, r, b = font.getbbox(text)
            return r - l
        except Exception:
            return len(text) * size // 2

    def _bn_render_centered(self, img: Image.Image, text: str, y: int,
                            size: int, fill: RGB,
                            shadow: bool = False, shadow_offset: int = 2) -> None:
        tw = self._bn_width(text, size)
        x = (self.width - tw) // 2
        self._bn_render(img, text, x, y, size, fill,
                        shadow=shadow, shadow_offset=shadow_offset)

    # ───────────────────────────────── fonts ─────────────────────────────

    def _find_alt_font(self) -> Optional[str]:
        candidates = [
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for cand in candidates:
            if os.path.isfile(cand):
                return cand
        return None

    def _find_bangla_font(self, prefer_regular: bool = False) -> Optional[str]:
        # Resolve relative paths against the repo root + module dir
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
