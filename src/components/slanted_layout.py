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
    return _usable_source_rows(rows) if 1 <= len(rows) <= 12 else []


def _usable_source_rows(rows):
    """Убрать ложно-тонкую полосу, которая душит общий кегль всех строк."""
    if not rows or len(rows) < 2:
        return rows
    heights = [float(row[3]) for row in rows]
    median_h = float(np.median(heights))
    kept = [row for row in rows if float(row[3]) >= median_h * 0.4]
    return kept if kept else rows


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
    rows = _usable_source_rows(list(geometry.get('source_lines') or []))
    if not rows or len(text) > 2000 or len(text.split()) > 160:
        return None
    if geometry.get('readable_caption') and (not frozen or frozen.get('caption')) and not (
            style.font_size_override or style.letter_spacing or style.line_spacing):
        return _caption_raster(text, font_path, style, geometry, rows, scale, frozen)
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
    if frozen:
        # Повторный рендер обязан учитывать увеличенный кегль свободных строк.
        layer = layer.resize((max(1, int(frozen["width"])), max(1, int(frozen["height"]))), Image.Resampling.LANCZOS)
        fit = dict(frozen)
    return layer, fit


def _caption_raster(text, font_path, style, geometry, rows, scale, frozen=None):
    """Максимально читаемые строки в общем поле карточки, без мелкого общего кегля.

    Пробуем число строк по реальным глифам. Промежутки исходных строк
    доступны переводу, но поворот и внешние границы остаются исходными.
    """
    font = ImageFont.truetype(str(font_path), 144)
    if frozen:
        alpha = glyph_mask(frozen['text'], font, stroke_width=3, line_spacing=20).resize(
            (int(frozen['width']), int(frozen['height'])), Image.Resampling.LANCZOS)
        layer = Image.new('RGBA', alpha.size, tuple(style.fill_rgb)+(255,))
        layer.putalpha(alpha)
        return layer, dict(frozen)
    left, top = min(r[0] for r in rows), min(r[1] for r in rows)
    width = max(r[0]+r[2] for r in rows)-left
    height = max(r[1]+r[3] for r in rows)-top
    center = (left+width/2, top+height/2)
    height += 2*float(geometry.get('caption_padding', 0))
    bx, by, bw, bh = geometry['source_bbox']
    ix, iy, iw, ih = geometry['ink_bbox']
    matrix = cv2.getRotationMatrix2D((bx+bw/2, by+bh/2), float(style.rotation), 1.)
    cx, cy = matrix @ np.array([*center, 1.])
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    pad = (max(0., float(style.stroke_width)) if style.stroke_mode == 'custom'
           else float(geometry.get('outline_px', 0)) if style.stroke_mode == 'auto' else 0.)
    room_x = max(1., min(cx-ix, ix+iw-cx)-pad-2)
    room_y = max(1., min(cy-iy, iy+ih-cy)-pad-2)
    best = None
    for count in range(1, min(6, len(text.split()))+1):
        lines = _split_lines(text, [width]*count, font, 0)
        if not lines:
            continue
        alpha = glyph_mask('\n'.join(lines), font, stroke_width=3, line_spacing=20)
        factor = min(max(1, width-2*pad)/alpha.width, max(1, height-2*pad)/alpha.height,
                     2*room_x/max(1, cosine*alpha.width+sine*alpha.height),
                     2*room_y/max(1, sine*alpha.width+cosine*alpha.height))
        score = (factor, -abs(count-len(rows)))
        if best is None or score > best[0]:
            best = (score, alpha, lines)
    if best is None:
        return None
    _, alpha, lines = best
    factor = min(best[0][0], 8192/max(alpha.size)/scale)
    alpha = alpha.resize((max(1, round(alpha.width*factor*scale)),
                          max(1, round(alpha.height*factor*scale))), Image.Resampling.LANCZOS)
    layer = Image.new('RGBA', alpha.size, tuple(style.fill_rgb)+(255,))
    layer.putalpha(alpha)
    fit = dict(text='\n'.join(lines), width=alpha.width, height=alpha.height,
               center=list(center), spacing=0, line_gap=20, font_size=max(1, round(144*factor)),
               writing_mode='horizontal', caption=True)
    return layer, fit
