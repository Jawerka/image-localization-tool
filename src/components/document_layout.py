"""Определение печатных документов и полная раскладка внутри прямоугольника."""

import math
from functools import cache

import cv2
import numpy as np


def is_document_page(rgb, regions):
    """Крупный свободный абзац на однородном фоне, а не форма облачка."""
    from src.components.text_regions import _ink_components, _line_boxes

    height, width = rgb.shape[:2]
    for region in regions:
        x, y, w, h = region.bbox
        if (
            region.bubble_bbox is not None
            or w * h < height * width * 0.12
            or h < w * 0.18
        ):
            continue
        crop = rgb[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]
        if min(crop.shape[:2], default=0) < 4:
            continue
        border = np.concatenate(
            (
                crop[:2].reshape(-1, 3),
                crop[-2:].reshape(-1, 3),
                crop[:, :2].reshape(-1, 3),
                crop[:, -2:].reshape(-1, 3),
            )
        )
        bg = np.median(border, axis=0)
        uniform = np.mean(np.linalg.norm(border.astype(float) - bg, axis=1) < 24)
        lines = _line_boxes(_ink_components(crop))
        broad = [line for line in lines if line[2] > w * 0.5]
        if uniform > 0.85 and len(broad) >= 4:
            return True
    return False


def _colour_islands(crop):
    """Крупные цветные пятна (фото), не буквы колонки."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1]
    chroma = np.ptp(crop, axis=2)
    med_sat = float(np.median(sat))
    colorful = ((sat > med_sat + 25) & (chroma > 35)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(colorful)
    islands = np.zeros(crop.shape[:2], np.uint8)
    crop_area = crop.shape[0] * crop.shape[1]
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if area < 80:
            continue
        if area > crop_area * .04 or min(width, height) > min(crop.shape[:2]) * .22:
            islands[labels == index] = 255
    if np.any(islands):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        islands = cv2.dilate(islands, kernel)
    return islands


def document_layout_mask(image_rgb, region):
    """Прямоугольник колонки без фото и крупных цветных островов."""
    height, width = image_rgb.shape[:2]
    x, y, box_w, box_h = region.bbox
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + box_w), min(height, y + box_h)
    mask = np.zeros((height, width), np.uint8)
    mask[y0:y1, x0:x1] = 255
    crop = image_rgb[y0:y1, x0:x1]
    if min(crop.shape[:2]) < 8:
        return mask
    local = np.ones(crop.shape[:2], np.uint8) * 255
    islands = _colour_islands(crop)
    if np.any(islands):
        local[islands > 0] = 0
    ink = document_ink(crop)
    if np.count_nonzero(ink) > 50:
        _ys, xs = np.where(ink)
        pad = max(6, int(round((xs.max() - xs.min() + 1) * .06)))
        column = np.zeros_like(local)
        column[:, max(0, int(xs.min()) - pad):min(local.shape[1], int(xs.max()) + 1 + pad)] = 255
        combined = np.minimum(local, column)
        if np.mean(combined > 0) > .15:
            local = combined
    if np.mean(local > 0) < .12:
        local = np.ones(crop.shape[:2], np.uint8) * 255
        if np.any(islands):
            local[islands > 0] = 0
    if not np.any(local):
        return mask
    mask[y0:y1, x0:x1] = local
    return mask


def document_paint_mask(image_rgb, region):
    """Можно рисовать везде, кроме цветных фото-островов в рамке документа."""
    height, width = image_rgb.shape[:2]
    allowed = np.full((height, width), 255, np.uint8)
    x, y, box_w, box_h = region.bbox
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + box_w), min(height, y + box_h)
    crop = image_rgb[y0:y1, x0:x1]
    if min(crop.shape[:2]) < 8:
        return allowed
    islands = _colour_islands(crop)
    if np.any(islands):
        allowed[y0:y1, x0:x1][islands > 0] = 0
    return allowed


def document_ink(crop):
    """Исключить аватары и крупные значки по высоте относительно букв."""
    from src.components.text_regions import _ink_components

    ink = _ink_components(crop)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    substantial = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 12]
    if len(substantial) < 8:
        return ink
    typical = float(
        np.percentile([stats[i, cv2.CC_STAT_HEIGHT] for i in substantial], 60)
    )
    keep = []
    for i in substantial:
        if stats[i, cv2.CC_STAT_HEIGHT] > max(8, typical * 1.7):
            continue
        pixels = crop[labels == i].astype(float)
        chroma = pixels - pixels.mean(axis=1, keepdims=True)
        if float(chroma.std(axis=0).mean()) > 12:
            continue
        keep.append(i)
    result = np.isin(labels, keep).astype(np.uint8)
    # Диакритика относится к строке под ней, а не к отдельному абзацу.
    kernel = max(3, round(typical * 0.2))
    return cv2.morphologyEx(result, cv2.MORPH_CLOSE, np.ones((kernel, 1), np.uint8))


def layout_rectangle(
    text,
    font,
    draw,
    spans,
    hyphenator,
    align,
    strict=True,
    letter_spacing=0.0,
    line_spacing=0.0,
    stroke_pad=0,
):
    """Перенос по прямоугольнику с привязкой к верху и учётом границ глифов."""
    words = text.split()
    if not words:
        return [], True
    rows = [y for y, s in enumerate(spans) if s is not None]
    if not rows:
        return [], False
    top, bottom = rows[0], rows[-1] + 1
    pad = max(1, int(stroke_pad)) + 1
    left = max(spans[y][0] for y in rows) + pad
    right = min(spans[y][1] for y in rows) - pad
    available = right - left + 1
    if available < 1:
        return [], False

    @cache
    def box(line):
        b = font.getbbox(line)
        extra = (len(line) - 1) * letter_spacing if letter_spacing else 0
        width = (
            draw.textlength(line, font=font)
            if not letter_spacing
            else sum(draw.textlength(ch, font=font) for ch in line) + extra
        )
        return min(0, b[0]), b[1], max(math.ceil(width), b[2] + extra), b[3]

    pending = list(words)
    lines = []
    current = ""
    index = 0
    while index < len(pending):
        word = pending[index]
        trial = f"{current} {word}" if current else word
        b = box(trial)
        if b[2] - b[0] <= available:
            current = trial
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            continue
        cuts = hyphenator.positions(word) if hyphenator else []
        cuts = [
            p
            for p in cuts
            if p >= 3
            and len(word) - p >= 3
            and box(word[:p] + "-")[2] - box(word[:p] + "-")[0] <= available
        ]
        if not cuts:
            # URL и слова вне словаря переносим без добавления символов.
            cuts = [
                p for p in range(1, len(word))
                if box(word[:p])[2] - box(word[:p])[0] <= available
            ]
            if not cuts:
                return [], False
            p = max(cuts)
            lines.append(word[:p])
            pending[index] = word[p:]
            continue
        p = max(cuts)
        lines.append(word[:p] + "-")
        pending[index] = word[p:]
    if current:
        lines.append(current)
    glyph_top = min(box(s)[1] for s in lines)
    glyph_bottom = max(box(s)[3] for s in lines)
    ink_h = glyph_bottom - glyph_top
    size = getattr(font, "size", 12)
    advance = max(ink_h + 2, round(size * 1.1 + line_spacing))
    block_h = (len(lines) - 1) * advance + ink_h
    if block_h + 2 * pad > bottom - top:
        return [], False
    placed = []
    for i, line in enumerate(lines):
        a, _, b, _ = box(line)
        width = b - a
        x = (
            right - width + 1
            if align == "right"
            else (left + right - width + 1) // 2 if align == "center" else left
        )
        placed.append((line, int(x - a), int(top + pad + i * advance - glyph_top)))
    return placed, True
