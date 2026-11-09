"""Чернила звука: обводка на пёстром фоне и линии рисунка.

Прямоугольник по кропу появляется, когда порог по кольцу бокса
принимает фон за буквы. Здесь буква подтверждается обводкой
противоположного цвета ограниченной толщины.
"""

from __future__ import annotations

import cv2
import numpy as np

_MIN_LETTERS = 2


def outlined_glyphs(crop: np.ndarray, *, reject_cut_cores: bool = False) -> np.ndarray | None:
    """Буквы с контрастной обводкой в обеих полярностях.

    Возвращает маску букв и самой обводки или None, если таких букв меньше двух.
    Фон за обводкой не входит: рост останавливается, когда кольцо перестаёт
    быть цветом обводки, и не доходит до упора по толщине.
    Площадь выбирает полярность. Другая побеждает, только если у большей
    разброс толщины штриха большой, а у меньшей штрих ровный и толще 1.5 px.
    """
    if crop.ndim != 3 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    candidates = []
    for dark_core in (True, False):
        mask, letters, widths = _polarity(gray, dark_core, reject_cut_cores=reject_cut_cores)
        pixels = int(np.count_nonzero(mask))
        if letters >= _MIN_LETTERS and pixels > 0:
            candidates.append((mask, pixels, widths))
    best = _choose_polarity(candidates)
    if best is None:
        return None
    # Низ буквы на чёрном фоне не имеет белой обводки и сливается с заливкой.
    # Добираем только несколько соседних тёмных пикселей, не всю заливку.
    best = _absorb_dark_edge(gray, best, steps=3)
    # Толстый белый stroke на тёмном поле дальше sandwich-лимита 6 px.
    if float(np.median(gray)) < 140:
        best = _absorb_light_halo(gray, best, steps=12)
    return _drop_edge_components(best)


def _choose_polarity(candidates: list[tuple[np.ndarray, int, list[float]]]) -> np.ndarray | None:
    """Площадь главная. Ровный штрих заменяет пёструю полярность рисунка."""
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda item: item[1], reverse=True)
    winner, _pixels, widths = ordered[0]
    if len(ordered) < 2:
        return winner
    other, _other_pixels, other_widths = ordered[1]
    other_median = float(np.median(other_widths)) if other_widths else 0.0
    if _variation(widths) > 0.8 and _variation(other_widths) < 0.5 and other_median > 1.5:
        return other
    return winner


def _variation(widths: list[float]) -> float:
    """Коэффициент вариации полуширины штриха. Одной компоненте разброса нет."""
    if len(widths) < 2:
        return 0.0
    mean = float(np.mean(widths))
    if mean <= 1e-6:
        return 0.0
    return float(np.std(widths) / mean)


def _polarity(gray: np.ndarray, dark_core: bool, *, reject_cut_cores: bool = False) -> tuple[np.ndarray, int, list[float]]:
    """Одна полярность: тёмное ядро и тонкая обводка между ядром и фоном."""
    if dark_core:
        core_px = gray <= 80
        # Скринтон около 180 не обводка: у наклейки ореол почти белый.
        halo_px = gray >= 215
    else:
        core_px = gray >= 215
        halo_px = gray <= 60
    core_u8 = core_px.astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(core_u8)
    dist = cv2.distanceTransform(core_u8, cv2.DIST_L2, 3)
    result = np.zeros(gray.shape, np.uint8)
    cores = np.zeros(gray.shape, np.uint8)
    letters = 0
    widths: list[float] = []
    sizes: list[tuple[int, int]] = []
    height, width = gray.shape
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        # При поиске расширенной рамки обрезанный рисунок не подтверждает букву.
        if reject_cut_cores and (x == 0 or y == 0 or x+w == width or y+h == height):
            continue
        if area < 8 or w < 2 or h < 2:
            continue
        if area > width * height * 0.3:
            continue
        if w > width * 0.92 and h > height * 0.92:
            continue
        # Полоса рамки на всю ширину или высоту кропа — не буква.
        if _spans_opposite(x, y, w, h, width, height):
            continue
        fill = area / float(w * h)
        if not 0.12 <= fill <= 0.75:
            continue
        limit = min(6, max(2, int(round(min(h, w) * 0.4))))
        y0, x0 = max(0, y - limit), max(0, x - limit)
        y1, x1 = min(height, y + h + limit), min(width, x + w + limit)
        local_core = labels[y0:y1, x0:x1] == index
        body = _sandwich(local_core, halo_px[y0:y1, x0:x1], limit)
        if body is None:
            continue
        component = labels == index
        half = float(dist[component].max()) if np.any(component) else 0.0
        letters += _letter_count(w, h)
        widths.append(half)
        sizes.append((w, h))
        cores[component] = 255
        result[y0:y1, x0:x1] = np.maximum(result[y0:y1, x0:x1], body)
    if len(sizes) == 1:
        letters = _letter_count(sizes[0][0], sizes[0][1], sole=True)
    result = _cut_thick_masses(result, cores, widths)
    return result, letters, widths


def _spans_opposite(x: int, y: int, w: int, h: int, width: int, height: int) -> bool:
    """Компонента касается левого и правого края или верхнего и нижнего."""
    horizontal = x <= 1 and x + w >= width - 1
    vertical = y <= 1 and y + h >= height - 1
    return horizontal or vertical


def _cut_thick_masses(mask: np.ndarray, cores: np.ndarray, widths: list[float]) -> np.ndarray:
    """Убрать массу рисунка, которая толще букв, и обводку вокруг неё.

    Радиус открытия — 2.2 медианной полуширины. Тонкий штрих буквы,
    примыкающий к массе, остаётся.
    """
    if not widths or int(np.count_nonzero(cores)) < 16:
        return mask
    median = float(np.median(widths))
    if median < 1.0:
        return mask
    radius = max(2, int(round(median * 2.2)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    mass = cv2.morphologyEx((cores > 0).astype(np.uint8), cv2.MORPH_OPEN, kernel) > 0
    if int(np.count_nonzero(mass)) < 16:
        return mask
    thin = (cores > 0) & ~mass
    protect = cv2.dilate(thin.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0
    adjacent_radius = max(2, int(round(median)))
    adjacent_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (adjacent_radius * 2 + 1, adjacent_radius * 2 + 1),
    )
    adjacent = (cv2.dilate(mass.astype(np.uint8), adjacent_kernel) > 0) & ~protect
    kept = (mask > 0) & ~(mass | adjacent)
    return kept.astype(np.uint8) * 255


def _sandwich(core: np.ndarray, halo: np.ndarray, limit: int) -> np.ndarray | None:
    """Обводка — пиксели ореола между ядром и другим фоном, не толще limit.

    Край большой белой области далеко от ядра. Плоское белое поле не имеет
    «другой стороны», поэтому обычный текст на бумаге сюда не попадает.
    """
    outside = ~halo & ~core
    if int(np.count_nonzero(outside)) < 8 or int(np.count_nonzero(halo)) < 8:
        return None
    dist_core = cv2.distanceTransform((~core).astype(np.uint8), cv2.DIST_L2, 3)
    dist_out = cv2.distanceTransform((~outside).astype(np.uint8), cv2.DIST_L2, 3)
    stroke = halo & (dist_core <= limit) & (dist_out <= limit)
    core_count = int(np.count_nonzero(core))
    stroke_count = int(np.count_nonzero(stroke))
    if stroke_count < 8 or not 0.2 <= stroke_count / core_count <= 2.4:
        return None
    ring = (dist_core >= 1) & (dist_core <= 2.5)
    ring_count = int(np.count_nonzero(ring))
    if ring_count < 8:
        return None
    if float(np.count_nonzero(stroke & ring) / ring_count) < 0.55:
        return None
    near_stroke = cv2.dilate(stroke.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    bridge = (~core) & (~halo) & (dist_core <= 2) & near_stroke
    body = (core | stroke | bridge).astype(np.uint8) * 255
    if int(np.count_nonzero(body)) < 12:
        return None
    return body


def _absorb_light_halo(gray: np.ndarray, mask: np.ndarray, steps: int) -> np.ndarray:
    """Добрать белую обводку вокруг уже найденных ядер, не заливая бумагу."""
    reached = mask > 0
    light = gray >= 215
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _step in range(steps):
        ring = (cv2.dilate(reached.astype(np.uint8), kernel) > 0) & light & ~reached
        if not np.any(ring):
            break
        reached = reached | ring
    return reached.astype(np.uint8) * 255


def _absorb_dark_edge(gray: np.ndarray, mask: np.ndarray, steps: int) -> np.ndarray:
    """Присоединить тёмные пиксели вплотную к уже найденным буквам."""
    reached = mask > 0
    dark = gray <= 85
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _step in range(steps):
        ring = (cv2.dilate(reached.astype(np.uint8), kernel) > 0) & dark & ~reached
        if not np.any(ring):
            break
        reached = reached | ring
    return reached.astype(np.uint8) * 255


def _drop_edge_components(mask: np.ndarray) -> np.ndarray | None:
    """Убрать фрагмент рисунка у края кропа, если он не содержит центр надписи."""
    # Узкая перемычка к рисунку рвётся, сама буква остаётся.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    eroded = cv2.erode((mask > 0).astype(np.uint8), kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(eroded)
    if count <= 1:
        return mask if int(np.count_nonzero(mask)) >= 12 else None
    height, width = mask.shape
    center_x, center_y = width / 2.0, height / 2.0
    kept = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < 8:
            continue
        touches = x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1
        covers = (x - 4) <= center_x <= (x + w + 4) and (y - 4) <= center_y <= (y + h + 4)
        if touches and not covers:
            continue
        kept.append(index)
    filtered = cv2.dilate(np.isin(labels, kept).astype(np.uint8), kernel)
    filtered = (filtered > 0) & (mask > 0)
    # Внутренние компоненты уже прошли проверку обводки. Открытие нужно
    # только для перемычек к краевому рисунку: иначе оно стирает тонкие штрихи.
    raw_count, raw_labels, raw_stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8))
    internal = []
    for index in range(1, raw_count):
        x, y, w, h, area = (int(v) for v in raw_stats[index])
        if area >= 8 and x > 1 and y > 1 and x + w < width - 1 and y + h < height - 1:
            internal.append(index)
    filtered |= np.isin(raw_labels, internal)
    if int(np.count_nonzero(filtered)) < 12:
        return None
    return filtered.astype(np.uint8) * 255


def _letter_count(width: int, height: int, sole: bool = False) -> int:
    """Слипшиеся жирные буквы — одна компонента, но несколько букв по пропорции.

    Единственная очень вытянутая компонента — полоса, а не слово из многих букв.
    Умеренное слово из одной компоненты по-прежнему считается несколькими буквами.
    """
    short = max(1, min(width, height))
    long = max(width, height)
    count = max(1, int(round(long / short * 0.85)))
    if sole and long >= short * 6:
        return 1
    return count


def outline_pad_px(ink: np.ndarray, pixel_scale: float = 1.0) -> float:
    """Отступ маски, когда обводка уже входит в чернила.

    Берётся от меньшей стороны буквы и не превышает прежние 8 px,
    чтобы запасной путь без обводки оставался отдельным.
    """
    scale = float(pixel_scale or 1.0)
    count, _labels, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8))
    sides = [
        int(min(stats[index, cv2.CC_STAT_WIDTH], stats[index, cv2.CC_STAT_HEIGHT]))
        for index in range(1, count)
        if stats[index, cv2.CC_STAT_AREA] >= 8
    ]
    if not sides:
        return 4.0 * scale
    # Меньшая сторона часто принадлежит целому слову, а не одной букве.
    # Обводка уже в маске, поэтому отступ остаётся коротким.
    letter = float(np.median(sides))
    # Обводка уже в чернилах. 2–3 px: больший отступ на эталоне давал лишний край.
    return float(min(3.0 * scale, max(2.0 * scale, round(letter * 0.12))))


def drop_line_components(binary: np.ndarray) -> np.ndarray:
    """Убрать тонкие длинные линии рисунка рядом с буквами.

    Маска не меняется, если после фильтра остаётся меньше трёх букв:
    одинокая черта может быть самим звуком.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8))
    if count <= 3:
        return binary
    records = []
    for index in range(1, count):
        _x, _y, w, h, area = (int(v) for v in stats[index])
        if area < 4:
            continue
        short = max(1, min(w, h))
        long = max(w, h)
        records.append((index, short, long, area, w, h))
    if len(records) < 3:
        return binary
    body = [short for _index, short, long, _area, _w, _h in records if long < short * 3.5]
    if len(body) < 3:
        body = [short for _index, short, _long, _area, _w, _h in records]
    typical = float(np.median(body))
    kept = []
    for index, short, long, _area, _w, _h in records:
        line = long >= short * 4 and long >= typical * 3 and short <= max(2.0, typical * 0.65)
        if not line:
            kept.append(index)
    if len(kept) < 3:
        return binary
    band = _text_band(stats, kept)
    if band is not None:
        banded = [index for index in kept if _in_band(stats[index], band)]
        if len(banded) >= 3:
            kept = banded
    filtered = np.isin(labels, kept)
    result = filtered.astype(np.uint8) * 255
    kept_pixels = int(np.count_nonzero(result))
    # Тонкий звук сам похож на линию. Если фильтр съел больше трети, это он.
    if kept_pixels < 12 or kept_pixels < int(np.count_nonzero(binary)) * 0.65:
        return binary
    return result


def _text_band(stats: np.ndarray, kept: list[int]) -> tuple[np.ndarray, np.ndarray, float, float] | None:
    """Полоса строки по центрам букв: точка, нормаль, середина и допуск."""
    centers = []
    for index in kept:
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < 8 or max(w, h) > min(w, h) * 3.2:
            continue
        centers.append((x + w / 2.0, y + h / 2.0, float(max(w, h))))
    if len(centers) < 3:
        return None
    points = np.array([(x, y) for x, y, _span in centers], dtype=np.float64)
    mean = points.mean(axis=0)
    _values, vectors = np.linalg.eigh(np.cov((points - mean).T))
    direction = vectors[:, int(np.argmax(_values))]
    normal = np.array([-direction[1], direction[0]])
    offsets = (points - mean) @ normal
    span = float(np.median([item[2] for item in centers]))
    # Несколько строк: компонента остаётся, если она рядом с любой из них.
    return mean, normal, offsets, span * 0.85


def _in_band(stat: np.ndarray, band: tuple[np.ndarray, np.ndarray, np.ndarray, float]) -> bool:
    """Центр компоненты рядом с одной из строк, а не строго на их медиане."""
    mean, normal, offsets, limit = band
    x, y, w, h = (int(v) for v in stat[:4])
    center = np.array([x + w / 2.0, y + h / 2.0])
    offset = float((center - mean) @ normal)
    return float(np.min(np.abs(offsets - offset))) <= limit
