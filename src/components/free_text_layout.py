"""Растровая основа свободной надписи с безопасными буквами и нативным наклоном."""
from __future__ import annotations

import math
import textwrap
import cv2
import numpy as np
from PIL import Image, ImageFont

from src.components.glyph_layout import glyph_mask, vertical_glyph_mask


def free_raster(text, font_path, style, geometry, scale=2, frozen=None):
    """Основа до геометрии; фиксированные размеры снимка сохраняют ручной поворот."""
    if geometry.get('source_lines'):
        from src.components.slanted_layout import line_raster
        result = line_raster(text, font_path, style, geometry, scale, frozen)
        if result is not None:
            return result
    font = ImageFont.truetype(str(font_path), 144)
    ix, iy, width, height = geometry.get('ink_bbox', [0, 0, 100, 50])
    ink_width, ink_height = width, height
    # Внешняя обводка входит в доступную рамку, не утолщая сами глифы.
    pad = float(geometry.get('outline_px', 0)) if style.stroke_mode == 'auto' else (
        max(0., float(style.stroke_width)) if style.stroke_mode == 'custom' else 0.)
    reserve = pad + (2 if pad else 0)
    width, height = max(1, width - 2 * reserve), max(1, height - 2 * reserve)
    mode = (frozen or {}).get('writing_mode', geometry.get('writing_mode', 'auto'))
    original_text = text
    if frozen:
        text = frozen['text']
    elif mode != 'vertical' and '\n' not in text and len(text.split()) > 1 and width / height < 3:
        limit = max(6, round(math.sqrt(len(text) * max(.4, width / height) * 1.8)))
        text = '\n'.join(textwrap.wrap(text, width=limit, break_long_words=False, break_on_hyphens=False))
    reference_factor = 144 / max(1, style.font_size_override or style.font_size)
    spacing = float(style.letter_spacing or 0) * reference_factor
    line_gap = max(0, 20 + style.line_spacing * reference_factor)
    if frozen:
        spacing = float(frozen.get('spacing', spacing))
        line_gap = float(frozen.get('line_gap', line_gap))
    alpha = glyph_mask(text, font, 0, spacing=spacing, line_spacing=line_gap)
    # Старый снимок без режима обязан сохранить прежнюю форму букв.
    if frozen and 'writing_mode' not in frozen:
        alpha = glyph_mask(text, font, 3, spacing=spacing, line_spacing=line_gap)
    alpha = alpha.resize((max(1, round(alpha.width * .9)), alpha.height), Image.Resampling.LANCZOS)
    vertical = None
    if mode == 'vertical' or (not frozen and mode == 'auto' and
            geometry.get('allow_vertical', False) and height >= width * 1.7 and
            2 <= sum(not ch.isspace() for ch in original_text) <= 24 and
            not style.font_size_override and abs(float(style.rotation)) <= 12):
        vertical = vertical_glyph_mask(original_text, font, spacing=spacing, line_spacing=line_gap)
    if vertical is not None:
        horizontal_fit = min(width / max(1, alpha.width), height / max(1, alpha.height))
        vertical_fit = min(width / max(1, vertical.width), height / max(1, vertical.height))
        if mode == 'vertical' or vertical_fit >= horizontal_fit * 1.3:
            alpha, text, mode = vertical, original_text, 'vertical'
    if mode != 'vertical':
        mode = 'horizontal'
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
    if not frozen and mode == 'vertical' and geometry.get('kind') == 'bubble' and not style.font_size_override:
        points = geometry.get('contour')
        if isinstance(points, list) and len(points) >= 3:
            # Вытянутый баллон сужается сверху и снизу: одной AABB недостаточно.
            bx, by, bw, bh = geometry.get('ink_bbox', [ix, iy, width, height])
            cw, ch = max(1, int(bw)), max(1, int(bh))
            if max(cw, ch) <= 8192:
                allowed = np.zeros((ch, cw), np.uint8)
                polygon = np.asarray(points, dtype=np.float64) - (bx, by)
                cv2.fillPoly(allowed, [np.round(polygon).astype(np.int32)], 255)
                inset = max(1, math.ceil(pad + 2))
                allowed = cv2.erode(allowed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (inset*2+1,inset*2+1)))
                for _ in range(180):
                    aw, ah = max(1,round(base_w/scale)), max(1,round(base_h/scale))
                    if aw <= cw and ah <= ch:
                        sample = np.asarray(alpha.resize((aw,ah),Image.Resampling.LANCZOS)) > 15
                        left,top=(cw-aw)//2,(ch-ah)//2
                        if not np.any(sample & (allowed[top:top+ah,left:left+aw] == 0)):
                            break
                    if base_w == 1 and base_h == 1:
                        break
                    base_w,base_h=max(1,int(base_w*.96)),max(1,int(base_h*.96))
    # Поля и ореол измерены в исходных пикселях, после подбора размера.
    cap = min(1., 8192 / max(base_w, base_h))
    base_w, base_h = max(1, round(base_w * cap)), max(1, round(base_h * cap))
    alpha = alpha.resize((base_w, base_h), Image.Resampling.LANCZOS)
    layer = Image.new('RGBA', alpha.size, tuple(style.fill_rgb) + (255,))
    layer.putalpha(alpha)
    # После вращения вокруг рамки центр должен остаться в центре исходных чернил.
    bx, by, bw, bh = geometry.get('source_bbox', geometry.get('ink_bbox', [0, 0, width, height]))
    cx, cy = bx + bw / 2, by + bh / 2
    dx, dy = ix + ink_width / 2 - cx, iy + ink_height / 2 - cy
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
                  spacing=spacing, line_gap=line_gap, font_size=font_size, writing_mode=mode)
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
