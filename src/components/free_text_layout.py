"""Растровая основа свободной надписи с безопасными буквами и нативным наклоном."""
from __future__ import annotations

import math
import textwrap
import cv2
import numpy as np
from PIL import Image, ImageFont

from src.components.glyph_layout import glyph_mask


def free_raster(text, font_path, style, geometry, scale=2, frozen=None):
    """Основа до геометрии; фиксированные размеры снимка сохраняют ручной поворот."""
    font = ImageFont.truetype(str(font_path), 144)
    ix, iy, width, height = geometry.get('ink_bbox', [0, 0, 100, 50])
    width, height = max(1, width), max(1, height)
    if frozen:
        text = frozen['text']
    elif '\n' not in text and len(text.split()) > 1 and width / height < 3:
        limit = max(6, round(math.sqrt(len(text) * max(.4, width / height) * 1.8)))
        text = '\n'.join(textwrap.wrap(text, width=limit, break_long_words=False, break_on_hyphens=False))
    reference_factor = 144 / max(1, style.font_size_override or style.font_size)
    spacing = float(style.letter_spacing or 0) * reference_factor
    line_gap = max(0, 20 + style.line_spacing * reference_factor)
    if frozen:
        spacing = float(frozen.get('spacing', spacing))
        line_gap = float(frozen.get('line_gap', line_gap))
    alpha = glyph_mask(text, font, 3, spacing=spacing, line_spacing=line_gap)
    alpha = alpha.resize((max(1, round(alpha.width * .9)), alpha.height), Image.Resampling.LANCZOS)
    reference_h = alpha.height
    turned = alpha.rotate(float(style.rotation), Image.Resampling.BICUBIC, expand=True)
    bounds = turned.getbbox()
    if frozen:
        base_w, base_h = int(frozen['width']), int(frozen['height'])
    else:
        tw, th = (bounds[2] - bounds[0], bounds[3] - bounds[1]) if bounds else turned.size
        factor = min(width / max(1, tw), height / max(1, th))
        if style.font_size_override > 0:
            factor = style.font_size_override / 144.
        base_w, base_h = max(1, round(alpha.width * factor * scale)), max(1, round(alpha.height * factor * scale))
    # Поля и ореол измерены в исходных пикселях, после подбора размера.
    cap = min(1., 8192 / max(base_w, base_h))
    base_w, base_h = max(1, round(base_w * cap)), max(1, round(base_h * cap))
    alpha = alpha.resize((base_w, base_h), Image.Resampling.LANCZOS)
    layer = Image.new('RGBA', alpha.size, tuple(style.fill_rgb) + (255,))
    layer.putalpha(alpha)
    # После вращения вокруг рамки центр должен остаться в центре исходных чернил.
    bx, by, bw, bh = geometry.get('source_bbox', geometry.get('ink_bbox', [0, 0, width, height]))
    cx, cy = bx + bw / 2, by + bh / 2
    dx, dy = ix + width / 2 - cx, iy + height / 2 - cy
    if bounds:
        factor = base_h / max(1, reference_h * scale)
        dx -= ((bounds[0] + bounds[2]) / 2 - turned.width / 2) * factor
        dy -= ((bounds[1] + bounds[3]) / 2 - turned.height / 2) * factor
    angle = math.radians(float(style.rotation))
    center = [cx + math.cos(angle) * dx - math.sin(angle) * dy,
              cy + math.sin(angle) * dx + math.cos(angle) * dy]
    if frozen and isinstance(frozen.get('center'), list) and len(frozen['center']) == 2:
        center = frozen['center']
    font_size = max(1, round(144 * base_h / max(1, reference_h * scale)))
    if frozen:
        font_size = int(frozen.get('font_size', font_size))
    fitted = dict(text=text, width=base_w, height=base_h, center=center,
                  spacing=spacing, line_gap=line_gap, font_size=font_size)
    return layer, fitted


def outline_layer(layer, color, width):
    """Обводка общей alpha не стирает соседние глифы."""
    if color is None or width <= 0:
        return layer
    radius = max(1, round(width))
    alpha = np.array(layer.getchannel('A'))
    expanded = cv2.dilate(alpha, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)))
    under = Image.new('RGBA', layer.size, tuple(color) + (255,))
    under.putalpha(Image.fromarray(expanded))
    under.alpha_composite(layer)
    return under
