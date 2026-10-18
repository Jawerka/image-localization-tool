"""Интерьер речевого баллона для маски ретуши (без AABB-эллипса).

Силуэт объединяет достаточно крупные светлые компоненты у текста,
ограниченные цветом и градиентной обводкой. Отступ внутрь задаётся
Config.bubble_mask_inset_px.
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
    seed_local = _seed_in_crop(crop, region, x0, y0)
    if seed_local is None:
        return empty

    sx, sy = seed_local
    seed_color = crop[sy, sx].astype(np.float32)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    dist = np.linalg.norm(crop.astype(np.float32) - seed_color, axis=2)
    dark = gray.astype(np.float32) < (float(gray[sy, sx]) - _DARK_DELTA)
    edges = cv2.Canny(gray, 60, 140) > 0
    barrier = dark | edges
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
    text_probe=probe[max(0,ty-y0):min(probe.shape[0],ty+th-y0),max(0,tx-x0):min(probe.shape[1],tx+tw-x0)]
    if text_probe.size and np.mean(text_probe)<.5:
        return empty
    # В сером прозрачном облачке панель может разорвать фон на разные оттенки.
    # Неполная заливка оставит буквы; цветные фигурные облачка имеют иные боксы.
    chroma=np.max(crop,axis=2).astype(float)-np.min(crop,axis=2)
    if text_probe.size and np.mean(chroma)<8 and np.mean(text_probe)<.9:
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


def _seed_in_crop(
    crop: np.ndarray,
    region: TextRegion,
    origin_x: int,
    origin_y: int,
) -> tuple[int, int] | None:
    """Светлый пиксель у центра текста (фон облачка, не буква)."""
    ch, cw = crop.shape[:2]
    tx, ty, tw, th = region.bbox
    cx = float(tx + tw / 2) - origin_x
    cy = float(ty + th / 2) - origin_y
    cx = min(max(cx, 0.0), cw - 1.0)
    cy = min(max(cy, 0.0), ch - 1.0)

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    xa, ya = max(0, tx - origin_x), max(0, ty - origin_y)
    xb, yb = min(cw, tx + tw - origin_x), min(ch, ty + th - origin_y)
    if xb <= xa or yb <= ya:
        return None
    patch = gray[ya:yb, xa:xb]
    # Медиана всего кропа на тёмном рисунке допускает пиксели букв.
    ys, xs = np.where(patch >= float(np.percentile(patch, 85)) - 8.0)
    ys, xs = ys + ya, xs + xa
    if ys.size == 0:
        return None
    nearest = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
    return int(xs[nearest]), int(ys[nearest])


def _label_from_seed(fillable: np.ndarray, sx: int, sy: int) -> np.ndarray | None:
    """Разметка связных компонент; None если seed не в fillable."""
    if fillable[sy, sx] == 0:
        return None
    num, labels = cv2.connectedComponents(fillable, connectivity=4)
    if num <= 1:
        return None
    return labels
