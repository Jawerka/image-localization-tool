"""Геометрический варп изображения: дуга, кольцо, волна, перспектива, сетка 4×4.

Без моделей. Карты для ``cv2.remap`` — обратные: ``map_x[y, x]``, ``map_y[y, x]``
задают координату исходного пикселя, из которого берётся выходной пиксель ``(x, y)``.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["build_remap", "warp_image"]


def warp_image(
    rgba: np.ndarray,
    kind: str,
    bend: float = 0.0,
    quad: list | None = None,
    mesh: list | None = None,
) -> np.ndarray:
    """Вернуть деформированную копию изображения того же размера.

    ``kind``:
    - ``none`` и неизвестные значения — копия без изменений;
    - ``arc`` — дуга строки по вертикали (середина вверх/вниз),
      ``bend`` — доля высоты (обычно −1..1);
    - ``ring`` — кольцевой изгиб вокруг центра;
    - ``wave`` — синусоидальный сдвиг по горизонтали и вертикали;
    - ``flag`` — одноосный «флаг»: вертикальный сдвиг по горизонтальной фазе;
    - ``perspective`` — ``quad`` из 4 точек назначения ``[x, y]`` в порядке
      TL, TR, BR, BL. В них переходят углы исходного прямоугольника
      ``(0, 0), (w-1, 0), (w-1, h-1), (0, h-1)``. Холст остаётся того же размера;
    - ``mesh`` — 16 точек назначения row-major (``row * 4 + col``): ряд — ось Y
      сверху вниз, столбец — ось X слева направо. Точки соответствуют регулярной
      исходной сетке ``linspace(0, w-1, 4)`` × ``linspace(0, h-1, 4)``.

    Пустой или крошечный кадр (сторона меньше 2 пикселей) возвращается копией.
    Каналы (3 или 4) и ``uint8`` сохраняются.
    """
    if not isinstance(rgba, np.ndarray) or rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        return np.array(rgba, copy=True)

    image = rgba.copy()
    height, width = image.shape[:2]
    if image.size == 0 or height < 2 or width < 2:
        return image

    key = kind.strip().lower() if isinstance(kind, str) else ""
    if key == "arc":
        map_x, map_y = build_remap("arc", height, width, bend)
        return _remap(image, map_x, map_y)
    if key == "ring":
        map_x, map_y = build_remap("ring", height, width, bend)
        return _remap(image, map_x, map_y)
    if key == "wave":
        map_x, map_y = build_remap("wave", height, width, bend)
        return _remap(image, map_x, map_y)
    if key == "flag":
        map_x, map_y = build_remap("flag", height, width, bend)
        return _remap(image, map_x, map_y)
    if key == "perspective":
        return _warp_perspective(image, quad)
    if key == "mesh":
        return _warp_mesh(image, mesh)
    return image


def build_remap(
    kind: str,
    height: int,
    width: int,
    bend: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Обратные карты ``map_x``, ``map_y`` формы ``(height, width)``, ``float32``.

    Для ``arc``, ``ring``, ``wave`` и ``flag`` при ``bend == 0`` карты совпадают с
    координатной сеткой. Остальные виды дают тождественные карты.
    """
    height = int(height)
    width = int(width)
    if height < 1 or width < 1:
        empty = np.zeros((max(height, 0), max(width, 0)), dtype=np.float32)
        return empty, empty.copy()

    key = kind.strip().lower() if isinstance(kind, str) else ""
    amount = float(bend)
    if key == "arc":
        pair = _map_arc(height, width, amount)
    elif key == "ring":
        pair = _map_ring(height, width, amount)
    elif key == "wave":
        pair = _map_wave(height, width, amount)
    elif key == "flag":
        pair = _map_flag(height, width, amount)
    else:
        pair = _identity_maps(height, width)
    return _finite_maps(*pair)


def _identity_maps(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    map_x = np.empty((height, width), dtype=np.float32)
    map_y = np.empty((height, width), dtype=np.float32)
    map_x[:] = np.arange(width, dtype=np.float32)[None, :]
    map_y[:] = np.arange(height, dtype=np.float32)[:, None]
    return map_x, map_y


def _finite_maps(
    map_x: np.ndarray,
    map_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    map_x = np.nan_to_num(map_x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
    map_y = np.nan_to_num(map_y, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
    return np.ascontiguousarray(map_x), np.ascontiguousarray(map_y)


def _remap(image: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    map_x, map_y = _finite_maps(map_x, map_y)
    return cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _map_arc(height: int, width: int, bend: float) -> tuple[np.ndarray, np.ndarray]:
    """Вертикальный изгиб строки: середина поднимается/опускается. ``bend == 0`` — тождество.

    Положительный ``bend`` («дугой вверх») поднимает середину; отрицательный —
    опускает. Сдвиг по Y, ноль у левого и правого края.
    """
    map_x, map_y = _identity_maps(height, width)
    if bend == 0.0 or width < 2:
        return map_x, map_y
    xs = np.arange(width, dtype=np.float32)[None, :]
    center_x = np.float32((width - 1) * 0.5)
    nx = (xs - center_x) / max(center_x, np.float32(1.0))
    # Максимум в середине ширины, ноль на боковых кромках.
    shift = np.float32(bend) * np.float32(height) * (1.0 - nx * nx)
    # Обратный remap: map_y = y + shift при bend>0 берёт пиксель снизу → середина едет вверх.
    map_y = map_y + shift
    return map_x, map_y


def _map_ring(height: int, width: int, bend: float) -> tuple[np.ndarray, np.ndarray]:
    """Кольцевой изгиб: закрутка и лёгкое радиальное сжатие. ``bend == 0`` — тождество."""
    map_x, map_y = _identity_maps(height, width)
    if bend == 0.0 or height < 2 or width < 2:
        return map_x, map_y
    ys, xs = np.indices((height, width), dtype=np.float32)
    center_x = np.float32((width - 1) * 0.5)
    center_y = np.float32((height - 1) * 0.5)
    dx = xs - center_x
    dy = ys - center_y
    radius = np.sqrt(dx * dx + dy * dy)
    radius_max = np.float32(max(float(center_x), float(center_y), 1.0))
    norm = radius / radius_max
    # Масштаб не уходит в ноль при типичных bend около −1..1.
    scale = np.maximum(1.0 + np.float32(bend) * np.float32(0.2) * norm, np.float32(0.05))
    dx = dx / scale
    dy = dy / scale
    angle = np.float32(bend) * norm
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    map_x = center_x + dx * cos_a + dy * sin_a
    map_y = center_y - dx * sin_a + dy * cos_a
    return map_x, map_y


def _map_wave(height: int, width: int, bend: float) -> tuple[np.ndarray, np.ndarray]:
    """Синус по Y сдвигает X, синус по X сдвигает Y. ``bend == 0`` — тождество."""
    map_x, map_y = _identity_maps(height, width)
    if bend == 0.0 or height < 2 or width < 2:
        return map_x, map_y
    ys = np.arange(height, dtype=np.float32)[:, None]
    xs = np.arange(width, dtype=np.float32)[None, :]
    phase_y = ys * (np.float32(2.0 * np.pi) / np.float32(max(height - 1, 1)))
    phase_x = xs * (np.float32(2.0 * np.pi) / np.float32(max(width - 1, 1)))
    amp_x = np.float32(bend) * np.float32(width) * np.float32(0.08)
    amp_y = np.float32(bend) * np.float32(height) * np.float32(0.08)
    map_x = map_x - amp_x * np.sin(phase_y)
    map_y = map_y - amp_y * np.sin(phase_x)
    return map_x, map_y


def _map_flag(height: int, width: int, bend: float) -> tuple[np.ndarray, np.ndarray]:
    """Одноосный флаг: только Y сдвигается по фазе X. ``bend == 0`` — тождество."""
    map_x, map_y = _identity_maps(height, width)
    if bend == 0.0 or height < 2 or width < 2:
        return map_x, map_y
    xs = np.arange(width, dtype=np.float32)[None, :]
    phase_x = xs * (np.float32(2.0 * np.pi) / np.float32(max(width - 1, 1)))
    amp_y = np.float32(bend) * np.float32(height) * np.float32(0.12)
    map_y = map_y - amp_y * np.sin(phase_x)
    return map_x, map_y


def _parse_quad(quad: list | None) -> np.ndarray | None:
    if quad is None:
        return None
    try:
        points = np.asarray(quad, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if points.shape != (4, 2) or not np.isfinite(points).all():
        return None
    if _polygon_area(points) < 1.0:
        return None
    return points


def _polygon_area(points: np.ndarray) -> float:
    x = points[:, 0].astype(np.float64)
    y = points[:, 1].astype(np.float64)
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) * 0.5)


def _warp_perspective(image: np.ndarray, quad: list | None) -> np.ndarray:
    """Прямоугольник кадра → четырёхугольник ``quad`` (TL, TR, BR, BL)."""
    points = _parse_quad(quad)
    if points is None:
        return image
    height, width = image.shape[:2]
    source = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    try:
        matrix = cv2.getPerspectiveTransform(source, points)
    except cv2.error:
        return image
    if matrix is None or not np.isfinite(matrix).all():
        return image
    return cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _parse_mesh(mesh: list | None) -> np.ndarray | None:
    """16 точек row-major или массив ``(4, 4, 2)`` — точки назначения."""
    if mesh is None:
        return None
    try:
        points = np.asarray(mesh, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if points.shape == (16, 2):
        points = points.reshape(4, 4, 2)
    elif points.shape != (4, 4, 2):
        return None
    if not np.isfinite(points).all():
        return None
    return points


def _warp_mesh(image: np.ndarray, mesh: list | None) -> np.ndarray:
    """Бикубическое поле смещения контрольных точек, затем ``cv2.remap``."""
    points = _parse_mesh(mesh)
    if points is None:
        return image
    height, width = image.shape[:2]
    src_x = np.linspace(0.0, width - 1.0, 4, dtype=np.float64)
    src_y = np.linspace(0.0, height - 1.0, 4, dtype=np.float64)
    grid_x = np.broadcast_to(src_x, (4, 4))
    grid_y = np.broadcast_to(src_y[:, None], (4, 4))
    disp_x = (points[:, :, 0] - grid_x).astype(np.float32)
    disp_y = (points[:, :, 1] - grid_y).astype(np.float32)
    full_x = cv2.resize(disp_x, (width, height), interpolation=cv2.INTER_CUBIC)
    full_y = cv2.resize(disp_y, (width, height), interpolation=cv2.INTER_CUBIC)
    map_x, map_y = _identity_maps(height, width)
    map_x = map_x - full_x
    map_y = map_y - full_y
    return _remap(image, map_x, map_y)
