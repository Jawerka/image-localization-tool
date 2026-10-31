"""Точное обратное отображение сетки 4×4 для текстовых RGBA-слоёв.

Сетка хранит узлы назначения в порядке row-major. Каждый прямоугольник исходной
сетки отображается билинейной поверхностью; обратные карты решаются итерациями
Ньютона в каждой ячейке. Версия 1 остаётся в ``text_warp`` для старых проектов.
"""

from __future__ import annotations

import numpy as np
import cv2

from src.components.text_warp import _remap


def _mesh_points(mesh) -> np.ndarray | None:
    try:
        points = np.asarray(mesh, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if points.shape == (16, 2):
        points = points.reshape(4, 4, 2)
    if points.shape != (4, 4, 2) or not np.isfinite(points).all():
        return None
    return points


def _cell_vectors(points: np.ndarray, row: int, col: int):
    p00 = points[row, col]
    p10 = points[row, col + 1]
    p01 = points[row + 1, col]
    p11 = points[row + 1, col + 1]
    a = p10 - p00
    b = p01 - p00
    c = p11 - p10 - p01 + p00
    return p00, a, b, c


def _valid_mesh(points: np.ndarray) -> bool:
    """Запретить инвертированные и вырожденные ячейки до построения карт."""
    for row in range(3):
        for col in range(3):
            _p, a, b, c = _cell_vectors(points, row, col)
            corners = (
                a[0] * b[1] - a[1] * b[0],
                a[0] * (b[1] + c[1]) - a[1] * (b[0] + c[0]),
                (a[0] + c[0]) * b[1] - (a[1] + c[1]) * b[0],
                (a[0] + c[0]) * (b[1] + c[1]) - (a[1] + c[1]) * (b[0] + c[0]),
            )
            if min(float(value) for value in corners) <= 1e-6:
                return False
    return True


def _solve_cell(target_x, target_y, p00, a, b, c):
    u = np.full(target_x.shape, 0.5, dtype=np.float64)
    v = np.full(target_y.shape, 0.5, dtype=np.float64)
    for _ in range(8):
        fx = p00[0] + u * a[0] + v * b[0] + u * v * c[0] - target_x
        fy = p00[1] + u * a[1] + v * b[1] + u * v * c[1] - target_y
        if max(float(np.max(np.abs(fx))), float(np.max(np.abs(fy)))) <= 1e-6:
            break
        j00 = a[0] + v * c[0]
        j01 = b[0] + u * c[0]
        j10 = a[1] + v * c[1]
        j11 = b[1] + u * c[1]
        determinant = j00 * j11 - j01 * j10
        safe = np.abs(determinant) > 1e-9
        delta_u = np.zeros_like(u)
        delta_v = np.zeros_like(v)
        delta_u[safe] = (fx[safe] * j11[safe] - fy[safe] * j01[safe]) / determinant[safe]
        delta_v[safe] = (j00[safe] * fy[safe] - j10[safe] * fx[safe]) / determinant[safe]
        u -= delta_u
        v -= delta_v
    residual_x = p00[0] + u * a[0] + v * b[0] + u * v * c[0] - target_x
    residual_y = p00[1] + u * a[1] + v * b[1] + u * v * c[1] - target_y
    valid = (
        (np.abs(residual_x) <= 1e-3)
        & (np.abs(residual_y) <= 1e-3)
        & (u >= -1e-5)
        & (u <= 1.00001)
        & (v >= -1e-5)
        & (v <= 1.00001)
    )
    return u, v, valid


def invert_mesh_point(point, mesh, width: int, height: int) -> tuple[float, float] | None:
    """Найти исходную координату для точки назначения; используется общими fixtures."""
    points = _mesh_points(mesh)
    if points is None or width < 2 or height < 2 or not _valid_mesh(points):
        return None
    x, y = float(point[0]), float(point[1])
    source_x = np.linspace(0.0, width - 1.0, 4)
    source_y = np.linspace(0.0, height - 1.0, 4)
    for row in range(3):
        for col in range(3):
            cell = points[row:row + 2, col:col + 2].reshape(-1, 2)
            if not (cell[:, 0].min() - 1e-5 <= x <= cell[:, 0].max() + 1e-5
                    and cell[:, 1].min() - 1e-5 <= y <= cell[:, 1].max() + 1e-5):
                continue
            p00, a, b, c = _cell_vectors(points, row, col)
            u, v, valid = _solve_cell(np.asarray([x]), np.asarray([y]), p00, a, b, c)
            if valid[0]:
                return (
                    float(source_x[col] + u[0] * (source_x[col + 1] - source_x[col])),
                    float(source_y[row] + v[0] * (source_y[row + 1] - source_y[row])),
                )
    return None


def build_inverse_maps(mesh, width: int, height: int) -> tuple[np.ndarray, np.ndarray] | None:
    """Собрать обратные карты назначения → источника; None означает плохую сетку."""
    points = _mesh_points(mesh)
    if points is None or width < 2 or height < 2 or not _valid_mesh(points):
        return None
    map_x = np.full((height, width), -1.0, dtype=np.float32)
    map_y = np.full((height, width), -1.0, dtype=np.float32)
    assigned = np.zeros((height, width), dtype=bool)
    source_x = np.linspace(0.0, width - 1.0, 4)
    source_y = np.linspace(0.0, height - 1.0, 4)
    for row in range(3):
        for col in range(3):
            cell = points[row:row + 2, col:col + 2].reshape(-1, 2)
            left = max(0, int(np.floor(cell[:, 0].min())))
            right = min(width - 1, int(np.ceil(cell[:, 0].max())))
            top = max(0, int(np.floor(cell[:, 1].min())))
            bottom = min(height - 1, int(np.ceil(cell[:, 1].max())))
            if right < left or bottom < top:
                continue
            ys, xs = np.mgrid[top:bottom + 1, left:right + 1]
            p00, a, b, c = _cell_vectors(points, row, col)
            u, v, inside = _solve_cell(xs.astype(np.float64), ys.astype(np.float64), p00, a, b, c)
            polygon_points = np.asarray([
                points[row, col], points[row, col + 1],
                points[row + 1, col + 1], points[row + 1, col],
            ])
            polygon = np.round(polygon_points - np.asarray([left, top])).astype(np.int32)
            polygon_mask = np.zeros((bottom - top + 1, right - left + 1), dtype=np.uint8)
            cv2.fillConvexPoly(polygon_mask, polygon, 1)
            inside &= polygon_mask > 0
            view_assigned = assigned[top:bottom + 1, left:right + 1]
            take = inside & ~view_assigned
            if not np.any(take):
                continue
            local_x = map_x[top:bottom + 1, left:right + 1]
            local_y = map_y[top:bottom + 1, left:right + 1]
            local_x[take] = (source_x[col] + u[take] * (source_x[col + 1] - source_x[col])).astype(np.float32)
            local_y[take] = (source_y[row] + v[take] * (source_y[row + 1] - source_y[row])).astype(np.float32)
            view_assigned[take] = True
    if not np.any(assigned):
        return None
    return map_x, map_y


def warp_mesh_forward(image: np.ndarray, mesh) -> np.ndarray:
    """Прямо отобразить узлы сетки; вырожденная сетка оставляет слой без изменений."""
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] not in (3, 4):
        return np.array(image, copy=True)
    height, width = image.shape[:2]
    maps = build_inverse_maps(mesh, width, height)
    if maps is None:
        return image.copy()
    return _remap(image, *maps)
