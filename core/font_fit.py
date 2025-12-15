"""
Font size fitting utilities.

Given a text string and a target pixel box (w/h), find a point-size that renders
as large as possible while still fitting inside the box.
"""

from __future__ import annotations

import os
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _resolve_font_path(editor: Any | None, font_name: str | None) -> str | None:
    if editor is not None and font_name and hasattr(editor, "_get_font_path"):
        try:
            path = editor._get_font_path(font_name)
            if path and os.path.exists(path):
                return path
        except Exception:
            pass
    return None


def fit_font_size_pt(
    text: str,
    box_w_px: int,
    box_h_px: int,
    *,
    editor: Any | None = None,
    font_name: str | None = None,
    min_pt: int = 8,
    max_pt: int = 200,
    dpi: int = 96,
    padding_x_px: int = 6,
    padding_y_px: int = 2,
) -> int:
    """
    Compute a fitting font size in points (int).

    - Point->pixel conversion uses `px = pt * dpi / 72`, matching Px()'s 96DPI mapping.
    - Intended for single-line text (PowerPoint textbox word_wrap=False).
    """
    text = (text or "").strip()
    if not text:
        return max(min_pt, min(16, max_pt))

    box_w_px = int(box_w_px or 0)
    box_h_px = int(box_h_px or 0)
    if box_w_px <= 0 or box_h_px <= 0:
        return max(min_pt, min(16, max_pt))

    avail_w = max(1, box_w_px - int(padding_x_px))
    avail_h = max(1, box_h_px - int(padding_y_px))

    font_path = _resolve_font_path(editor, font_name)
    if not font_path:
        # Fallback: height-based estimate only.
        est = int(avail_h * 72 / dpi * 0.95)
        return max(min_pt, min(est, max_pt))

    draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def fits(pt: int) -> bool:
        px = max(1, int(round(pt * dpi / 72)))
        try:
            font = ImageFont.truetype(font_path, px)
        except Exception:
            return True
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except Exception:
            return True
        return w <= avail_w and h <= avail_h

    hi = min(max_pt, max(min_pt, int(avail_h * 72 / dpi * 1.8)))
    lo = min_pt
    best = min_pt

    for _ in range(12):
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return max(min_pt, min(best, max_pt))

