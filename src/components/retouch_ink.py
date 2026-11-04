"""Подтверждение светлых букв внутри уже найденного текстового региона."""

from __future__ import annotations

import cv2
import numpy as np


def confirmed_light_ink(crop: np.ndarray) -> tuple[np.ndarray | None, bool]:
    """Светлые штрихи на контрастном фоне либо белое ядро с чёрной обводкой.

    Большие светлые поля и рамки отбрасываются. Возвращается маска чернил
    до отступа ретуши и признак включённой в неё обводки.
    """
    if crop.ndim != 3 or min(crop.shape[:2]) < 8:
        return None, False
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    neutral = np.ptp(crop, axis=2) < 45
    white = (np.min(crop, axis=2) >= 210) & neutral
    # Просветы обычных чёрных букв на бумаге тоже окружены чёрным:
    # преобладающее белое поле не является белой сердцевиной наклейки.
    if float(np.mean(white)) > .5:
        return None, False
    dark_panel = float(np.percentile(gray, 50)) < 120 and float(np.percentile(gray, 70)) < 170
    if not dark_panel:
        enclosed = _inverse_outline(gray, white)
        if enclosed is not None:
            return enclosed, True
    bright = ((np.min(crop, axis=2) >= (180 if dark_panel else 210)) & neutral).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    seeds = np.zeros_like(gray)
    outlined_seeds = np.zeros_like(gray)
    accepted = 0
    sizes = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < 3 or min(w, h) < 2 or area > gray.size * .20:
            continue
        if x == 0 or y == 0 or x + w == width or y + h == height:
            continue
        if w > width * .9 or h > height * .9:
            continue
        body = labels[y:y+h, x:x+w] == index
        if not dark_panel:
            ya, xa = max(0, y-3), max(0, x-3)
            yb, xb = min(height, y+h+3), min(width, x+w+3)
            local = (labels[ya:yb, xa:xb] == index).astype(np.uint8)
            ring = (cv2.dilate(local, kernel) > 0) & (local == 0)
            if not np.any(ring):
                continue
            surround = gray[ya:yb, xa:xb][ring]
            core = float(np.median(gray[y:y+h, x:x+w][body]))
            if np.mean(surround < core - 28) < .60:
                continue
            # Цветное облачко не является чёрной обводкой: расширение
            # по тёмным пикселям допускается только для подтверждённой оболочки.
            if np.mean(surround < 100) >= .60:
                outlined_seeds[y:y+h, x:x+w][body] = 255
        seeds[y:y+h, x:x+w][body] = 255
        accepted += 1
        sizes.append(min(w, h))
    if accepted < 2 or np.mean(seeds > 0) > .35:
        return None, False
    if dark_panel or not np.any(outlined_seeds):
        return seeds, False
    # От белого ядра до внешней границы тёмной обводки. Фон и другие
    # несвязанные чёрные объекты не входят в геодезическое расширение.
    reached = outlined_seeds > 0
    dark = gray < 135
    steps = min(10, max(3, round(float(np.median(sizes)) * .65)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _ in range(steps):
        expanded = (cv2.dilate(reached.astype(np.uint8), kernel) > 0) & dark
        reached |= expanded
    return np.maximum(seeds, reached.astype(np.uint8) * 255), True


def _inverse_outline(gray: np.ndarray, white: np.ndarray) -> np.ndarray | None:
    """Замкнутая тёмная оболочка с белым ядром, включая сплошные I и L."""
    height, width = gray.shape
    dark = (gray < 120).astype(np.uint8)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = np.zeros_like(gray)
    letters = 0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 3 or x == 0 or y == 0 or x+w == width or y+h == height:
            continue
        if w*h > gray.size * .3:
            continue
        local = np.zeros((h, w), np.uint8)
        cv2.drawContours(local, [contour - (x, y)], -1, 255, -1)
        body = local > 0
        light = white[y:y+h, x:x+w] & body
        if np.count_nonzero(light) < 4 or not .08 < np.mean(light[body]) < .85:
            continue
        result[y:y+h, x:x+w] = np.maximum(result[y:y+h, x:x+w], local)
        letters += 1
    return result if letters >= 2 else None


def preserves_picture(crop: np.ndarray) -> bool:
    """Светлая плашка с рисунком/градиентом не является непрозрачной бумагой."""
    if not crop.size:
        return False
    # JPEG-ореолы вокруг плотного текста дают разброс светлых пикселей,
    # хотя большую часть непрозрачной бумаги составляет чистый белый фон.
    if np.mean(np.min(crop, axis=2) >= 250) > .5:
        return False
    # Отступ от тёмных штрихов исключает их сглаживание из оценки фона.
    # В прозрачной плашке и после отступа остаются разные оттенки рисунка.
    clear = cv2.erode((np.min(crop, axis=2) > 180).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    light = crop[clear].astype(np.float32)
    if len(light) < 12:
        return False
    lo, hi = np.percentile(light, [10, 90], axis=0)
    return bool(np.max(hi - lo) > 8)


def smooth_line_mask(crop: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Плотные обведённые строки на размытом фоне закрываются целиком.

    На детальном рисунке остаётся точная маска: прямоугольник строки там
    удалил бы лишние линии. Светлая оболочка/тёмное ядро сюда не направляются.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    exclude = cv2.dilate((ink > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    background = np.hypot(gx, gy)[~exclude]
    if background.size < 50 or np.percentile(background, 90) > 8:
        return ink
    # Белые сердцевины разделяют строки даже там, где их чёрные обводки
    # соприкасаются. По внешним контурам получался один прямоугольник абзаца.
    cores = (gray >= 230) & (ink > 0)
    counts = np.sum(cores, axis=1)
    rows = np.flatnonzero(counts >= max(5, gray.shape[1] * .012))
    if not len(rows):
        return ink
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
    groups = [group for group in groups if len(group) >= 5]
    if len(groups) < 2:
        return ink
    result = ink.copy()
    for group in groups:
        y0, y1 = int(group[0]), int(group[-1]) + 1
        xs = np.flatnonzero(np.any(ink[y0:y1] > 0, axis=0))
        if y1-y0 < 5 or len(xs) < 5:
            continue
        pad = max(1, min(6, round((y1-y0) * .12)))
        result[max(0, y0-pad):min(gray.shape[0], y1+pad), xs[0]:xs[-1]+1] = 255
    return result


def smooth_light_mask(crop: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """На гладком фоне скрыть также просветы между светлыми буквами.

    Узкие дырки оставляли в контексте восстановления цветные тени исходных
    штрихов. Оболочка надписи убирает этот контекст, не заполняя всё облачко.
    Детальный рисунок и резкие границы за пределами букв не расширяются.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    exclude = cv2.dilate((ink > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    background = np.hypot(gx, gy)[~exclude]
    if background.size < 50 or np.percentile(background, 90) > 8:
        return ink
    ys, xs = np.where(ink > 0)
    if len(xs) < 12:
        return ink
    hull = cv2.convexHull(np.column_stack((xs, ys)).astype(np.int32))
    result = np.zeros_like(ink)
    cv2.fillConvexPoly(result, hull, 255)
    return result


def boundary_ink(image, bbox, bounds):
    """Восстановить только подтверждённые компоненты, обрезанные краем ROI."""
    x, y, w, h = bbox
    pad = max(5, min(32, round(min(w, h) * .08)))
    a, b, c, d = bounds
    aa, bb, cc, dd = max(0, x-pad), max(0, y-pad), min(image.width, x+w+pad), min(image.height, y+h+pad)
    if (aa, bb, cc, dd) == bounds:
        return None
    extra, inverse = confirmed_light_ink(np.asarray(image.crop((aa, bb, cc, dd))))
    if extra is None or not inverse:
        return None
    _, labels = cv2.connectedComponents((extra > 0).astype(np.uint8))
    inside = np.zeros_like(extra, bool)
    inside[b-bb:d-bb, a-aa:c-aa] = True
    crossing = np.intersect1d(np.unique(labels[inside]), np.unique(labels[~inside]))
    crossing = crossing[crossing > 0]
    if not len(crossing):
        return None
    extra = np.isin(labels, crossing).astype(np.uint8) * 255
    extra = cv2.dilate(extra, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return extra, (aa, bb, cc, dd)
