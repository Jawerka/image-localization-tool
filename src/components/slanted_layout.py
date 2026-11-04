"""Исходные поля строк в системе координат до поворота свободной надписи."""
from __future__ import annotations

import math
import cv2
import numpy as np
from PIL import Image, ImageFont

from src.components.glyph_layout import glyph_mask


def source_lines(ink, origin, source_bbox, angle):
    """Измерить горизонтальные полосы после распрямления подтверждённых чернил."""
    ys, xs = np.where(ink > 0)
    if len(xs) < 20:
        return []
    bx, by, bw, bh = source_bbox
    pivot = (bx + bw / 2, by + bh / 2)
    matrix = cv2.getRotationMatrix2D(pivot, -angle, 1.)
    points = np.column_stack((xs + origin[0], ys + origin[1], np.ones(len(xs)))) @ matrix.T
    lo = np.floor(points.min(axis=0)).astype(int)
    coords = np.rint(points - lo).astype(int)
    shape = coords.max(axis=0) + 1
    if max(shape) > 8192:
        return []
    mask = np.zeros((shape[1], shape[0]), np.uint8)
    mask[coords[:, 1], coords[:, 0]] = 1
    counts = mask.sum(axis=1)
    active = counts >= max(2, counts.max() * .06)
    # Мелкие разрывы между диакритикой и основной строкой не создают новый ряд.
    active = cv2.morphologyEx(active.astype(np.uint8)[:, None], cv2.MORPH_CLOSE,
                              np.ones((3, 1), np.uint8))[:, 0] > 0
    edges = np.diff(np.pad(active.astype(int), (1, 1)))
    rows = []
    for top, bottom in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        yy, xx = np.where(mask[top:bottom])
        if len(xx) < max(12, len(xs) * .015):
            continue
        left, right = int(xx.min()), int(xx.max()) + 1
        if right - left < (bottom - top) * 1.3:
            return []
        rows.append([float(lo[0] + left), float(lo[1] + top),
                     float(right - left), float(bottom - top)])
    return rows if 1 <= len(rows) <= 12 else []


def _split_lines(text, widths, font, spacing):
    """Разделить перевод по словам с учётом относительной длины исходных строк."""
    explicit = text.split('\n')
    if len(explicit) == len(widths) and all(line.strip() for line in explicit):
        return explicit
    words = text.split()
    n = len(widths)
    if len(words) < n:
        return None
    lengths = [float(font.getlength(word)) + max(0, len(word)-1)*spacing for word in words]
    gap = float(font.getlength(' ')) + spacing
    total = sum(lengths) + gap * (len(words) - n)
    target = total / max(1, sum(widths))
    costs = {(0, 0): (0., [])}
    for line in range(n):
        for end in range(line + 1, len(words) - (n-line-1) + 1):
            options = []
            for start in range(line, end):
                previous = costs.get((line, start))
                if previous is None:
                    continue
                length = sum(lengths[start:end]) + gap * (end-start-1)
                error = (length / widths[line] - target) ** 2
                options.append((previous[0] + error, previous[1] + [' '.join(words[start:end])]))
            if options:
                costs[line+1, end] = min(options, key=lambda item: item[0])
    return costs.get((n, len(words)), (0, None))[1]


def line_raster(text, font_path, style, geometry, scale=2, frozen=None):
    """Новый свободный растр: строки сохраняют поля без растяжения самих глифов."""
    rows = geometry.get('source_lines')
    if not rows or len(text) > 2000 or len(text.split()) > 160:
        return None
    if (style.font_size_override or style.letter_spacing or style.line_spacing or
            (frozen and not frozen.get('source_lines'))):
        return None
    font = ImageFont.truetype(str(font_path), 144)
    lines = _split_lines(text, [r[2] for r in rows], font, 0)
    if lines is None:
        return None
    pad = max(0., float(style.stroke_width)) if style.stroke_mode == 'custom' else (
        float(geometry.get('outline_px', 0)) if style.stroke_mode == 'auto' else 0.)
    masks = [glyph_mask(line, font) for line in lines]
    factors = [min(max(1, w-2*pad)/max(1, m.width), max(1, h-2*pad)/max(1, m.height))
               for (_, _, w, h), m in zip(rows, masks)]
    # Разный кегль допустим только в той мере, в какой он был в исходных строках.
    common = min(factors)
    bx, by, bw, bh = geometry.get('source_bbox', geometry.get('ink_bbox', [0, 0, 1, 1]))
    ix, iy, iw, ih = geometry.get('ink_bbox', [bx, by, bw, bh])
    matrix = cv2.getRotationMatrix2D((bx+bw/2, by+bh/2), float(style.rotation), 1.)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    for (x, y, w, h), mask in zip(rows, masks):
        cx, cy = matrix @ np.array([x+w/2, y+h/2, 1.])
        # Исходные полосы могут иметь выступающие углы: после поворота
        # буквы с ореолом обязаны остаться внутри исходного внешнего ROI.
        room_x = max(1., min(cx-ix, ix+iw-cx)-pad-2)
        room_y = max(1., min(cy-iy, iy+ih-cy)-pad-2)
        common = min(common, 2*room_x/max(1, cosine*mask.width+sine*mask.height),
                     2*room_y/max(1, sine*mask.width+cosine*mask.height))
    left = min(r[0] for r in rows)
    top = min(r[1] for r in rows)
    right = max(r[0]+r[2] for r in rows)
    bottom = max(r[1]+r[3] for r in rows)
    width, height = max(1, math.ceil((right-left)*scale)), max(1, math.ceil((bottom-top)*scale))
    if max(width, height) > 8192:
        return None
    layer = Image.new('RGBA', (width, height))
    for (x, y, w, h), mask in zip(rows, masks):
        mask = mask.resize((max(1, round(mask.width*common*scale)),
                            max(1, round(mask.height*common*scale))), Image.Resampling.LANCZOS)
        part = Image.new('RGBA', mask.size, tuple(style.fill_rgb)+(255,))
        part.putalpha(mask)
        layer.alpha_composite(part, (round((x+w/2-left)*scale-mask.width/2),
                                     round((y+h/2-top)*scale-mask.height/2)))
    fit = dict(text='\n'.join(lines), width=width, height=height, center=[(left+right)/2, (top+bottom)/2],
               spacing=0, line_gap=0, font_size=max(1, round(144*common)),
               writing_mode='horizontal', source_lines=True)
    return layer, fit
