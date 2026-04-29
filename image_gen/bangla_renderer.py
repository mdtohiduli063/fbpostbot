"""Proper Bangla / Indic text shaping & rendering for Pillow.

Pillow's wheels on PyPI are not compiled with libraqm support, so the built-in
`ImageDraw.text()` cannot shape complex scripts like Bangla — vowel signs and
conjuncts come out in the wrong order. This module fixes that by using
HarfBuzz (via `uharfbuzz`) for shaping and FreeType (via `freetype-py`) for
glyph rasterisation, then composites each glyph bitmap onto a Pillow image.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Tuple

import freetype
import uharfbuzz as hb
from PIL import Image


@dataclass(frozen=True)
class _ShapedGlyph:
    gid: int
    x_advance: int      # in 26.6 fixed point from HarfBuzz (we use ints/64)
    y_advance: int
    x_offset: int
    y_offset: int


class BanglaTextRenderer:
    """Shape + render Bangla / complex-script text correctly onto PIL images."""

    def __init__(self, font_path: str):
        self.font_path = font_path
        with open(font_path, "rb") as f:
            self._font_blob = f.read()
        self._hb_face = hb.Face(self._font_blob)
        self._ft_face = freetype.Face(font_path)

    # ---------- shaping ----------

    def _shape(self, text: str, size_px: int) -> List[_ShapedGlyph]:
        font = hb.Font(self._hb_face)
        # 26.6 fixed point pixels: hb returns advances in `1/64 px` units
        font.scale = (size_px * 64, size_px * 64)
        try:
            hb.ot_font_set_funcs(font)
        except AttributeError:
            pass

        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        # Force script/lang for best Bangla shaping
        try:
            buf.script = "Beng"
            buf.language = "ben"
            buf.direction = "ltr"
        except Exception:
            pass

        hb.shape(font, buf, {"kern": True, "liga": True})

        infos = buf.glyph_infos
        positions = buf.glyph_positions
        return [
            _ShapedGlyph(
                gid=info.codepoint,
                x_advance=pos.x_advance,
                y_advance=pos.y_advance,
                x_offset=pos.x_offset,
                y_offset=pos.y_offset,
            )
            for info, pos in zip(infos, positions)
        ]

    # ---------- measurement ----------

    def text_width(self, text: str, size_px: int) -> int:
        if not text:
            return 0
        glyphs = self._shape(text, size_px)
        return sum(g.x_advance for g in glyphs) // 64

    def text_bbox(self, text: str, size_px: int) -> Tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) bounding box for the shaped text (origin at 0,0)."""
        if not text:
            return (0, 0, 0, 0)
        self._ft_face.set_pixel_sizes(0, size_px)
        ascent = self._ft_face.size.ascender // 64
        descent = self._ft_face.size.descender // 64
        width = self.text_width(text, size_px)
        return (0, -ascent, width, -descent)

    def line_height(self, size_px: int) -> int:
        self._ft_face.set_pixel_sizes(0, size_px)
        return self._ft_face.size.height // 64

    # ---------- rendering ----------

    def render(
        self,
        image: Image.Image,
        text: str,
        x: int,
        y: int,
        size_px: int,
        fill: Tuple[int, int, int] = (255, 255, 255),
        shadow: bool = False,
        shadow_offset: int = 2,
        shadow_fill: Tuple[int, int, int] = (0, 0, 0),
        shadow_alpha: int = 180,
    ) -> int:
        """Draw shaped text onto `image`. (x, y) is the top-left of the text box.

        Returns the total advance width of the rendered text (pixels).
        """
        if not text:
            return 0

        self._ft_face.set_pixel_sizes(0, size_px)
        ascent = self._ft_face.size.ascender // 64

        # Convert image to RGBA for alpha compositing if needed
        was_rgba = image.mode == "RGBA"
        canvas = image if was_rgba else image.convert("RGBA")

        glyphs = self._shape(text, size_px)
        pen_x = x
        pen_y = y + ascent  # baseline

        if shadow:
            self._draw_glyphs(
                canvas, glyphs,
                pen_x + shadow_offset, pen_y + shadow_offset,
                shadow_fill, alpha=shadow_alpha,
            )

        total_advance = self._draw_glyphs(canvas, glyphs, pen_x, pen_y, fill)

        if not was_rgba:
            image.paste(canvas.convert(image.mode))
        return total_advance

    def _draw_glyphs(
        self,
        canvas: Image.Image,
        glyphs: Iterable[_ShapedGlyph],
        pen_x: int,
        pen_y: int,
        fill: Tuple[int, int, int],
        alpha: int = 255,
    ) -> int:
        cx = pen_x
        cy = pen_y
        total = 0
        r, g, b = fill[:3]
        for gl in glyphs:
            self._ft_face.load_glyph(gl.gid, freetype.FT_LOAD_RENDER)
            slot = self._ft_face.glyph
            bitmap = slot.bitmap
            w, h, pitch = bitmap.width, bitmap.rows, bitmap.pitch
            if w > 0 and h > 0:
                # Build a Pillow mask, handling pitch != width
                if pitch == w:
                    mask = Image.frombytes("L", (w, h), bytes(bitmap.buffer))
                else:
                    mask = Image.frombytes("L", (pitch, h),
                                           bytes(bitmap.buffer)).crop((0, 0, w, h))
                if alpha != 255:
                    mask = mask.point(lambda p, a=alpha: int(p * a / 255))
                # Solid colour layer that will be masked onto canvas
                colour_layer = Image.new("RGBA", (w, h), (r, g, b, 255))
                ox = cx + (gl.x_offset // 64) + slot.bitmap_left
                oy = cy - (gl.y_offset // 64) - slot.bitmap_top
                canvas.paste(colour_layer, (ox, oy), mask)
            cx += gl.x_advance // 64
            cy -= gl.y_advance // 64
            total += gl.x_advance // 64
        return total


@lru_cache(maxsize=4)
def get_renderer(font_path: str) -> BanglaTextRenderer:
    return BanglaTextRenderer(font_path)
