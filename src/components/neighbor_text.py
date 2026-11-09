"""Защита соседних надписей, отсутствующих в переводимых регионах."""
from __future__ import annotations

import itertools
import math
import re

import cv2
import numpy as np

from src.components.text_discovery import _discovery_ocr, _source_word


def _same_reading(a, b):
    """Не принимать ошибку OCR или разную длину звука за отдельное слово."""
    if ''.join(k for k, _ in itertools.groupby(a)) == ''.join(k for k, _ in itertools.groupby(b)):
        return True
    if len(b) >= 3 and len(b) * 2 >= len(a) and b in a:
        return True
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) == len(b) + 1:
        return any(a[:i] + a[i+1:] == b for i in range(len(a)))
    if len(b) == len(a) + 1:
        return any(b[:i] + b[i+1:] == a for i in range(len(b)))
    return False


def _overlap(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    return max(0, min(x+w, xx+ww) - max(x, xx)) * max(0, min(y+h, yy+hh) - max(y, yy))


def protect_neighbor_text(image, regions, mask, *, warnings=None, words=None):
    """Сохранить уверенно прочитанное чужое слово с другой геометрией строки.

    Локальный OCR используется только как защита от стирания, без добавления
    текста к переводу. Ручная маска применяется вызывающей стороной позднее.
    """
    automatic = [r for r in regions if not r.manual and not r.edited and r.translation.strip()
                 and (r.auto_layout or {}).get('kind') in ('bubble', 'free')]
    if not automatic or not np.any(mask):
        return mask
    if words is None:
        try:
            words = _discovery_ocr()._words(image)
        except Exception as exc:
            if warnings is not None:
                warnings.append(f'Защита соседнего текста не проверена: {type(exc).__name__}')
            return mask
    for region in automatic:
        region.auto_layout.pop('protected_text', None)
    known = [_source_word(r.text) for r in regions]
    tokens = {_source_word(w) for r in regions for w in re.findall(r'\w+', r.text)}
    protected = np.zeros_like(mask)
    count = 0
    for word in words:
        wanted = _source_word(word.text)
        if (not word.quad or word.confidence < .98 or not 4 <= len(wanted) <= 20
                or not wanted.isalpha() or any(wanted in text for text in known)
                or any(_same_reading(wanted, token) for token in tokens)):
            continue
        quad = np.asarray(word.quad, dtype=np.float32)
        if quad.shape != (4, 2) or not np.all(np.isfinite(quad)):
            continue
        angle = math.degrees(math.atan2(quad[1, 1] - quad[0, 1], quad[1, 0] - quad[0, 0]))
        if any((r.manual or r.edited) and _overlap(word.bbox, r.bbox) > 0 for r in regions):
            continue
        owners = [r for r in automatic if _overlap(word.bbox, r.bbox) > 0
                  and abs((angle - r.style.rotation + 90) % 180 - 90) > 3]
        if not owners:
            continue
        part = np.zeros_like(mask)
        cv2.fillPoly(part, [quad.astype(np.int32)], 255)
        part = cv2.dilate(part, np.ones((7, 7), np.uint8))
        if np.count_nonzero((part > 0) & (mask > 0)) < 30:
            continue
        protected |= part
        for region in owners:
            region.auto_layout.setdefault('protected_text', []).append(quad.tolist())
        count += 1
        if count >= 64:
            break
    if not count:
        return mask
    result = mask.copy()
    result[protected > 0] = 0
    if warnings is not None:
        warnings.append(f'Сохранены соседние нераспознанные надписи: {count}')
    return result


def protected_text_mask(shape, region):
    """Запретить автоматической вёрстке рисовать поверх сохранённых слов."""
    if region.manual or region.edited or region.text_position is not None or region.layout_snapshot:
        return None
    polygons = (region.auto_layout or {}).get('protected_text')
    if not isinstance(polygons, list) or not 1 <= len(polygons) <= 64:
        return None
    mask = np.zeros(shape[:2], np.uint8)
    for polygon in polygons:
        try:
            points = np.asarray(polygon, dtype=np.float64)
            if points.shape != (4, 2) or not np.all(np.isfinite(points)) or np.any(np.abs(points) >= 1_000_000):
                continue
            cv2.fillPoly(mask, [points.astype(np.int32)], 255)
        except (TypeError, ValueError):
            continue
    try:
        pad = max(3, min(32, math.ceil(float((region.auto_layout or {}).get('outline_px', 3)))))
    except (TypeError, ValueError, OverflowError):
        pad = 3
    return cv2.dilate(mask, np.ones((pad*2+1, pad*2+1), np.uint8)) if np.any(mask) else None
