"""Оценка стиля звукоподражания по исходной маске чернил.

Без моделей: медиана цвета, дистанция до фона, ``minAreaRect`` и
квадратичная базовая линия по центрам компонент.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["estimate_style"]

# Отличие обводки от заливки в евклидовой норме RGB.
_STROKE_COLOR_DISTANCE = 35.0
# Ядро заливки: пиксели не ближе этой доли максимального радиуса к краю.
_CORE_RADIUS_RATIO = 0.65
# Почти прямая базовая линия: |bend| ниже порога → kind none.
_BEND_STRAIGHT = 0.05
_BEND_LIMIT = 0.6
_MIN_COMPONENT_AREA = 8


def estimate_style(image_rgb: np.ndarray, mask: np.ndarray) -> dict:
    """Частичные поля TextStyle: fill_rgb, stroke_rgb, stroke_width, stroke_mode, rotation, warp.

    ``warp`` — ``{kind, bend, quad, mesh}``. ``rotation`` — градусы против часовой.
    ``quad`` и ``mesh`` здесь всегда ``None``.

    Заливка — медиана RGB ядра маски (пиксели с дистанцией до фона не ниже
    65% максимума). Так толстый цветной ободок не перебивает внутренний цвет.
    Обводка — медиана пикселей кольца ``dilate − erode``, которые лежат внутри
    маски и заметно отличаются от заливки. Если такого кольца нет, ``stroke_rgb``
    совпадает с заливкой.

    ``stroke_width`` — 90-й перцентиль радиуса (distance transform чернил) × 2.
    ``stroke_mode`` всегда ``"auto"``.

    Угол: ``cv2.minAreaRect``. У OpenCV угол стороны ``width`` лежит в [-90, 0).
    Длинная сторона равна этому углу, если ``width >= height``, иначе
    ``angle + 90``. Знак инвертируем: ось Y кадра смотрит вниз, а положительный
    поворот вёрстки — против часовой и поднимает правый конец. Горизонтальная
    полоса около 0°, полоса вверх-вправо — положительный угол.

    Изгиб: центры связных компонент, ``y`` от ``x``, нормированного на [-1, 1].
    Коэффициент при ``x²`` — провис в пикселях (положительный, если концы ниже
    центра). ``bend = clip(провис / ширина, -0.6, 0.6)``. Меньше трёх компонент
    или почти прямая линия — ``kind`` ``"none"`` и ``bend`` 0.
    """
    prepared = _prepare(image_rgb, mask)
    if prepared is None:
        return _neutral()
    image, ink_u8 = prepared

    distance = cv2.distanceTransform(ink_u8, cv2.DIST_L2, 5)
    fill, stroke = _colors(image, ink_u8, distance)
    return {
        "fill_rgb": fill,
        "stroke_rgb": stroke,
        "stroke_width": _stroke_width(distance, ink_u8),
        "stroke_mode": "auto",
        "rotation": _rotation_degrees(ink_u8),
        "warp": _baseline_warp(ink_u8),
    }


def _neutral() -> dict:
    """Пустая маска: нейтральные поля, без падения."""
    return {
        "fill_rgb": [0, 0, 0],
        "stroke_rgb": [0, 0, 0],
        "stroke_width": 0.0,
        "stroke_mode": "auto",
        "rotation": 0.0,
        "warp": {"kind": "none", "bend": 0.0, "quad": None, "mesh": None},
    }


def _prepare(image_rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """RGB uint8 и маска 0/255 одного размера. Пустая маска — ``None``."""
    image = np.asarray(image_rgb)
    raw_mask = np.asarray(mask)
    if image.ndim == 2:
        image = np.stack([image, image, image], axis=-1)
    if image.ndim != 3 or image.shape[2] < 3:
        return None
    image = image[:, :, :3]
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)

    if raw_mask.ndim == 3:
        raw_mask = raw_mask[:, :, 0]
    if raw_mask.ndim != 2 or raw_mask.shape[:2] != image.shape[:2]:
        return None
    if not np.any(raw_mask):
        return None
    ink_u8 = np.where(raw_mask != 0, np.uint8(255), np.uint8(0))
    return image, ink_u8


def _as_rgb(values) -> list[int]:
    """Три канала 0–255."""
    rgb = []
    for value in np.asarray(values, dtype=np.float64).reshape(-1)[:3]:
        rgb.append(int(min(255, max(0, round(float(value))))))
    while len(rgb) < 3:
        rgb.append(0)
    return rgb


def _median_rgb(image: np.ndarray, selected: np.ndarray) -> list[int]:
    """Медиана RGB по булевой выборке. Пустая выборка — чёрный."""
    pixels = image[selected]
    if pixels.size == 0:
        return [0, 0, 0]
    return _as_rgb(np.median(pixels.reshape(-1, 3), axis=0))


def _colors(
    image: np.ndarray,
    ink_u8: np.ndarray,
    distance: np.ndarray,
) -> tuple[list[int], list[int]]:
    """Заливка ядра и обводка внешнего кольца маски."""
    ink = ink_u8 > 0
    peak = float(distance.max()) if np.any(ink) else 0.0
    if peak >= 1.5:
        core = ink & (distance >= peak * _CORE_RADIUS_RATIO)
        if int(np.count_nonzero(core)) < 4:
            core = ink
    else:
        core = ink
    fill = _median_rgb(image, core)

    kernel = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(ink_u8, kernel)
    eroded = cv2.erode(ink_u8, kernel)
    # Кольцо внутри маски: фон за краем в обводку не берём.
    edge = (dilated > eroded) & ink
    edge_pixels = image[edge]
    if edge_pixels.size == 0:
        return fill, list(fill)
    delta = edge_pixels.astype(np.float32) - np.asarray(fill, dtype=np.float32)
    differ = np.linalg.norm(delta, axis=1) >= _STROKE_COLOR_DISTANCE
    if int(np.count_nonzero(differ)) < 4:
        return fill, list(fill)
    return fill, _as_rgb(np.median(edge_pixels[differ], axis=0))


def _stroke_width(distance: np.ndarray, ink_u8: np.ndarray) -> float:
    """Полная толщина чернил: 90-й перцентиль радиуса, умноженный на 2."""
    radii = distance[ink_u8 > 0]
    if radii.size == 0:
        return 0.0
    return float(np.percentile(radii, 90) * 2.0)


def _rotation_degrees(ink_u8: np.ndarray) -> float:
    """Длинная сторона minAreaRect в градусах против часовой, диапазон (-90, 90]."""
    contours, _hierarchy = cv2.findContours(ink_u8, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    points = np.vstack([contour.reshape(-1, 2) for contour in contours])
    if points.shape[0] < 5:
        return 0.0
    try:
        (_center, (width, height), angle) = cv2.minAreaRect(points.astype(np.float32))
    except cv2.error:
        return 0.0
    # Сторона width повёрнута на angle; длинная ось — она или перпендикуляр.
    long_angle = float(angle) + 90.0 if float(width) < float(height) else float(angle)
    rotation = -long_angle
    while rotation <= -90.0:
        rotation += 180.0
    while rotation > 90.0:
        rotation -= 180.0
    if abs(rotation) < 1e-3:
        return 0.0
    return float(rotation)


def _baseline_warp(ink_u8: np.ndarray) -> dict:
    """Дуга по центрам букв. Прямая и короткий ряд — ``none``."""
    straight = {"kind": "none", "bend": 0.0, "quad": None, "mesh": None}
    _count, _labels, stats, centroids = cv2.connectedComponentsWithStats(ink_u8, connectivity=8)
    centers: list[tuple[float, float]] = []
    for index in range(1, int(stats.shape[0])):
        if int(stats[index, cv2.CC_STAT_AREA]) < _MIN_COMPONENT_AREA:
            continue
        center_x, center_y = centroids[index]
        centers.append((float(center_x), float(center_y)))
    if len(centers) < 3:
        return straight

    centers.sort(key=lambda point: point[0])
    xs = np.asarray([point[0] for point in centers], dtype=np.float64)
    ys = np.asarray([point[1] for point in centers], dtype=np.float64)
    span = float(xs.max() - xs.min())
    if span < 4.0:
        return straight
    x_norm = (xs - float(xs.mean())) / (span / 2.0)
    if np.unique(np.round(x_norm, 5)).size < 3:
        return straight
    try:
        sag, _slope, _offset = np.polyfit(x_norm, ys, 2)
    except (np.linalg.LinAlgError, ValueError):
        return straight
    # sag — вертикальный провис на концах относительно центра, в пикселях.
    bend = float(np.clip(float(sag) / span, -_BEND_LIMIT, _BEND_LIMIT))
    if abs(bend) < _BEND_STRAIGHT:
        return straight
    return {"kind": "arc", "bend": bend, "quad": None, "mesh": None}
