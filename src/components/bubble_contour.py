"""Интерьер речевого баллона для маски ретуши (без AABB-эллипса).

Силуэт объединяет достаточно крупные светлые компоненты у текста,
ограниченные цветом и градиентной обводкой. Отступ внутрь задаётся
Config.bubble_mask_inset_px. Затравка — мода фона баллона вне букв и ореола.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.models import TextRegion

_DEFAULT_INSET = 2
_ROI_PAD = 4
_SEED_BAND = 56.0
_DARK_DELTA = 45.0
_MIN_FILL_RATIO = 0.08
# Flood меньше этой доли бокса облачка — не интерьер, а случайное пятно.
_FLOOD_MIN_RATIO = 0.35
_LETTER_COVER = 0.80
_FLOOD_DIFF = 24
_SEED_COLOR_STEP = 8
_SEED_COLOR_TOL = 12.0
_LEAK_PAD_RATIO = 0.15
_LEAK_AREA_RATIO = 0.10


def balloon_seed(
    image_rgb: np.ndarray,
    region: TextRegion,
) -> tuple[int, int, np.ndarray] | None:
    """Пиксель фона баллона у текста: мода цвета вне букв и белого ореола.

    Координаты страницы. ``None``, если бокса нет или фон не нашли.
    """
    if region.bubble_bbox is None:
        return None
    height, width = image_rgb.shape[:2]
    bx, by, bw, bh = region.bubble_bbox
    x0, y0 = max(0, int(bx)), max(0, int(by))
    x1, y1 = min(width, int(bx + bw)), min(height, int(by + bh))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = image_rgb[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    tx, ty, tw, th = region.bbox
    xa, ya = max(0, int(tx) - x0), max(0, int(ty) - y0)
    xb, yb = min(crop.shape[1], int(tx + tw) - x0), min(crop.shape[0], int(ty + th) - y0)
    if xb <= xa or yb <= ya:
        return None
    patch = gray[ya:yb, xa:xb]
    light = float(np.percentile(patch, 85))
    letters = np.zeros(gray.shape, np.uint8)
    letters[ya:yb, xa:xb] = (patch < (light - _DARK_DELTA)).astype(np.uint8)
    rows = np.where(np.any(letters > 0, axis=1))[0]
    if rows.size:
        breaks = np.where(np.diff(rows) > 1)[0]
        starts = np.r_[rows[0], rows[breaks + 1]]
        ends = np.r_[rows[breaks], rows[-1]]
        line_h = int(np.median(ends - starts + 1))
    else:
        line_h = max(8, int(th))
    radius = max(3, int(round(line_h * 0.35)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    halo = cv2.dilate(letters, kernel)
    cand = (gray >= (light - 24.0)) & (halo == 0)
    if int(np.count_nonzero(cand)) < 12:
        outside = halo == 0
        if not np.any(outside):
            return None
        cand = outside & (gray >= float(np.percentile(gray[outside], 50)))
    text_mask = np.zeros(gray.shape, dtype=bool)
    text_mask[ya:yb, xa:xb] = True
    local = cand & text_mask
    if int(np.count_nonzero(local)) >= 12:
        cand = local
    ys, xs = np.where(cand)
    if ys.size == 0:
        dark_only = gray <= float(np.percentile(gray, 35))
        cand = (gray >= float(np.percentile(gray, 70))) & ~dark_only
        ys, xs = np.where(cand)
    if ys.size == 0:
        return None
    cx = float(tx + tw / 2) - x0
    cy = float(ty + th / 2) - y0
    order = np.argsort((xs - cx) ** 2 + (ys - cy) ** 2)
    near = order[: max(12, len(order) // 5)]
    pixels = crop[ys[near], xs[near]]
    quantized = (pixels.astype(np.int32) // _SEED_COLOR_STEP) * _SEED_COLOR_STEP
    packed = (quantized[:, 0] << 16) | (quantized[:, 1] << 8) | quantized[:, 2]
    values, counts = np.unique(packed, return_counts=True)
    mode = int(values[int(np.argmax(counts))])
    mode_color = np.array([(mode >> 16) & 255, (mode >> 8) & 255, mode & 255], dtype=np.float32)
    dist = np.linalg.norm(crop.astype(np.float32) - mode_color, axis=2)
    match = cand & (dist <= _SEED_COLOR_TOL)
    mys, mxs = np.where(match)
    if mys.size == 0:
        mys, mxs = ys, xs
    nearest = int(np.argmin((mxs - cx) ** 2 + (mys - cy) ** 2))
    sx, sy = int(mxs[nearest]), int(mys[nearest])
    return x0 + sx, y0 + sy, crop[sy, sx].astype(np.float32)


def bubble_interior_mask(
    image_rgb: np.ndarray,
    region: TextRegion,
    *,
    inset_px: int = _DEFAULT_INSET,
) -> np.ndarray:
    """Силуэт интерьера баллона в координатах страницы. Пусто — если не собрали.

    ``inset_px`` — сжатие силуэта внутрь эллиптическим ядром.
    """
    height, width = image_rgb.shape[:2]
    empty = np.zeros((height, width), dtype=np.uint8)
    if region.bubble_bbox is None:
        return empty

    bx, by, bw, bh = region.bubble_bbox
    if bw < 4 or bh < 4:
        return empty

    x0 = max(0, bx - _ROI_PAD)
    y0 = max(0, by - _ROI_PAD)
    x1 = min(width, bx + bw + _ROI_PAD)
    y1 = min(height, by + bh + _ROI_PAD)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return empty

    crop = image_rgb[y0:y1, x0:x1]
    seed = balloon_seed(image_rgb, region)
    if seed is None:
        return empty
    sx_page, sy_page, seed_color = seed
    sx, sy = int(sx_page - x0), int(sy_page - y0)
    if not (0 <= sx < crop.shape[1] and 0 <= sy < crop.shape[0]):
        return empty

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    dist = np.linalg.norm(crop.astype(np.float32) - seed_color, axis=2)
    dark = gray.astype(np.float32) < (float(gray[sy, sx]) - _DARK_DELTA)
    # Canny только на тёмных штрихах обводки: внутренняя граница двух светлых
    # половин облачка не должна рвать силуэт.
    edges = cv2.Canny(gray, 60, 140) > 0
    outline = edges & (gray.astype(np.float32) < (float(gray[sy, sx]) - 20.0))
    barrier = dark | outline
    barrier[sy, sx] = False

    fillable = (dist <= _SEED_BAND) & ~barrier
    fillable[sy, sx] = True

    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        fillable.astype(np.uint8), connectivity=4
    )
    tx, ty, tw, th = region.bbox
    text_labels = labels[
        max(0, ty - y0):max(0, min(y1 - y0, ty + th - y0)),
        max(0, tx - x0):max(0, min(x1 - x0, tx + tw - x0)),
    ]
    hits = np.bincount(text_labels.ravel(), minlength=count)
    # Фон одного облачка может распадаться на части на границе панелей.
    selected = [
        label for label in range(1, count)
        if hits[label] >= max(20, tw * th * 0.005)
        and stats[label, cv2.CC_STAT_AREA] >= bw * bh * 0.015
    ]
    interior = np.isin(labels, selected).astype(np.uint8) * 255
    contours, _ = cv2.findContours(interior, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return empty
    filled = np.zeros_like(interior)
    cv2.drawContours(filled, contours, -1, 255, thickness=-1)

    box_area = max(1, bw * bh)
    if int(np.sum(filled > 0)) < _MIN_FILL_RATIO * box_area:
        return empty

    # У незамкнутого/прозрачного облачка внешний фон может войти в компоненту.
    # Заливка такого контура уничтожит обводку: безопаснее маска отдельных букв.
    probe=cv2.erode(filled,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)))>0
    text_area=np.zeros_like(probe)
    xa,ya=max(0,tx-x0-5),max(0,ty-y0-5)
    xb,yb=min(probe.shape[1],tx+tw-x0+5),min(probe.shape[0],ty+th-y0+5)
    text_area[ya:yb,xa:xb]=True
    dark_outside=(gray<100)&probe&~text_area
    if np.count_nonzero(dark_outside)>max(50,np.count_nonzero(probe)*.005):
        return empty
    tya, tyb = max(0, ty - y0), min(probe.shape[0], ty + th - y0)
    txa, txb = max(0, tx - x0), min(probe.shape[1], tx + tw - x0)
    text_probe=probe[tya:tyb, txa:txb]
    if text_probe.size and np.mean(text_probe)<.5:
        return empty
    # В сером прозрачном облачке панель может разорвать фон на разные оттенки.
    # Неполная заливка оставит буквы; цветные фигурные облачка имеют иные боксы.
    chroma=np.max(crop,axis=2).astype(float)-np.min(crop,axis=2)
    if text_probe.size and np.mean(chroma)<8 and np.mean(text_probe)<.9:
        return empty

    letter_gray = gray[tya:tyb, txa:txb]
    letter_fill = filled[tya:tyb, txa:txb]
    if letter_gray.size:
        dark_txt = (
            letter_gray.astype(np.float32) < (float(gray[sy, sx]) - _DARK_DELTA)
        ).astype(np.uint8)
        n_comp, labels, stats, _ = cv2.connectedComponentsWithStats(dark_txt)
        box_h = max(1, tyb - tya)
        box_w = max(1, txb - txa)
        max_area = max(40, int(box_w * box_h * 0.04))
        sizes = [
            stats[i, cv2.CC_STAT_AREA]
            for i in range(1, n_comp)
            if 8 <= stats[i, cv2.CC_STAT_AREA] <= max_area
            and stats[i, cv2.CC_STAT_HEIGHT] <= box_h * 0.45
        ]
        typical = float(np.median(sizes)) if sizes else 24.0
        letter_ids = [
            i for i in range(1, n_comp)
            if 8 <= stats[i, cv2.CC_STAT_AREA] <= max(40, typical * 4.0)
            and stats[i, cv2.CC_STAT_HEIGHT] <= max(8, typical * 2.5)
            and stats[i, cv2.CC_STAT_WIDTH] <= max(12, typical * 3.0)
        ]
        letters = np.isin(labels, letter_ids)
        n_letters = int(np.count_nonzero(letters))
        if n_letters >= 20:
            covered = int(np.count_nonzero(letters & (letter_fill > 0)))
            if covered / n_letters < _LETTER_COVER:
                return empty

    if inset_px > 0:
        radius = int(inset_px)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
        )
        filled = cv2.erode(filled, kernel, iterations=1)
        if not np.any(filled):
            return empty

    out = empty.copy()
    out[y0:y1, x0:x1] = filled
    return out


def balloon_flood_mask(image_rgb: np.ndarray, region: TextRegion) -> np.ndarray | None:
    """Flood интерьера от затравки фона, обрезанный по ``bubble_bbox``.

    Сравнение с цветом затравки (фиксированный диапазон). Утечка за бокс
    облачка в полосе 15% его размера — ``None``. Дыры залиты.
    """
    if region.bubble_bbox is None:
        return None
    height, width = image_rgb.shape[:2]
    bx, by, bw, bh = region.bubble_bbox
    if bw < 4 or bh < 4 or height < 1 or width < 1:
        return None
    seed = balloon_seed(image_rgb, region)
    if seed is None:
        return None
    cx, cy, _color = seed
    cx = min(max(int(cx), 0), width - 1)
    cy = min(max(int(cy), 0), height - 1)
    flood_mask = np.zeros((height + 2, width + 2), np.uint8)
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    lo = (_FLOOD_DIFF, _FLOOD_DIFF, _FLOOD_DIFF)
    cv2.floodFill(bgr, flood_mask, (cx, cy), (255, 255, 255), lo, lo, flags)
    filled = flood_mask[1:-1, 1:-1]
    x0, y0 = max(0, int(bx)), max(0, int(by))
    x1, y1 = min(width, int(bx + bw)), min(height, int(by + bh))
    if x1 <= x0 or y1 <= y0:
        return None
    pad_x = max(2, int(round(bw * _LEAK_PAD_RATIO)))
    pad_y = max(2, int(round(bh * _LEAK_PAD_RATIO)))
    ex0, ey0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    ex1, ey1 = min(width, x1 + pad_x), min(height, y1 + pad_y)
    band = filled[ey0:ey1, ex0:ex1].copy()
    band[y0 - ey0:y1 - ey0, x0 - ex0:x1 - ex0] = 0
    if int(np.count_nonzero(band)) > _LEAK_AREA_RATIO * max(1, bw * bh):
        return None
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[y0:y1, x0:x1] = filled[y0:y1, x0:x1]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        closed = np.zeros_like(mask)
        cv2.drawContours(closed, contours, -1, 255, thickness=-1)
        mask = closed
    if int(np.sum(mask > 0)) < _FLOOD_MIN_RATIO * max(1, bw * bh):
        return None
    return mask


def _seed_in_crop(
    crop: np.ndarray,
    region: TextRegion,
    origin_x: int,
    origin_y: int,
) -> tuple[int, int] | None:
    """Локальные координаты затравки в кропе с началом ``(origin_x, origin_y)``."""
    page = np.zeros((origin_y + crop.shape[0], origin_x + crop.shape[1], 3), np.uint8)
    page[origin_y:origin_y + crop.shape[0], origin_x:origin_x + crop.shape[1]] = crop
    seed = balloon_seed(page, region)
    if seed is None:
        return None
    sx, sy, _ = seed
    return int(sx - origin_x), int(sy - origin_y)


def _label_from_seed(fillable: np.ndarray, sx: int, sy: int) -> np.ndarray | None:
    """Разметка связных компонент; None если seed не в fillable."""
    if fillable[sy, sx] == 0:
        return None
    num, labels = cv2.connectedComponents(fillable, connectivity=4)
    if num <= 1:
        return None
    return labels
