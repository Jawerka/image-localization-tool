"""Варп RGBA: дуга, кольцо, волна, перспектива и сетка 4×4.

Перспектива: ``quad`` — четыре точки назначения углов исходного прямоугольника
в порядке TL, TR, BR, BL. Углы ``(0, 0), (w-1, 0), (w-1, h-1), (0, h-1)``
переходят в эти точки, размер холста не меняется.

Обратный ход: M = getPerspectiveTransform(прямоугольник, quad),
обратные углы — образы углов прямоугольника под inv(M). Второй вызов
``warp_image(..., quad=обратные углы)`` собирает гомографию прямоугольник →
эти углы, то есть inv(M).

Сетка: 16 точек row-major, ряд — ось Y (сверху вниз), столбец — ось X.
``mesh[row * 4 + col] = [x, y]`` — точка назначения узла исходной сетки.
"""

import cv2
import numpy as np

from src.components.text_warp import build_remap, warp_image


def _gradient(height: int, width: int, channels: int = 4) -> np.ndarray:
    """Плавный градиент и яркая метка в центре — сдвиг ломает сравнение."""
    image = np.zeros((height, width, channels), dtype=np.uint8)
    xs = np.linspace(16, 240, width, dtype=np.float32)
    ys = np.linspace(12, 230, height, dtype=np.float32)
    image[:, :, 0] = xs[None, :].astype(np.uint8)
    image[:, :, 1] = ys[:, None].astype(np.uint8)
    if channels == 4:
        image[:, :, 2] = 96
        image[:, :, 3] = 255
    else:
        image[:, :, 2] = 96
    cy, cx = height // 2, width // 2
    image[cy - 1:cy + 2, cx - 1:cx + 2, 0] = 10
    image[cy, cx, 0] = 255
    image[cy, cx, 1] = 1
    return image


def _marker_image(height: int = 80, width: int = 100) -> np.ndarray:
    image = np.zeros((height, width, 4), dtype=np.uint8)
    cy, cx = height // 2, width // 2
    image[cy - 4:cy + 5, cx - 4:cx + 5, 0] = 255
    image[cy - 4:cy + 5, cx - 4:cx + 5, 3] = 255
    return image


def _centroid(channel: np.ndarray, threshold: float = 200.0) -> tuple[float, float]:
    weight = channel.astype(np.float64)
    weight[weight < threshold] = 0.0
    total = float(weight.sum())
    assert total > 0.0
    ys, xs = np.indices(channel.shape)
    return float((weight * xs).sum() / total), float((weight * ys).sum() / total)


def _inverse_destination_quad(height: int, width: int, quad: list) -> list:
    """Углы назначения для гомографии, обратной к прямоугольник → ``quad``."""
    rect = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(rect, np.asarray(quad, dtype=np.float32))
    inverse = np.linalg.inv(matrix)
    homo = np.concatenate([rect.astype(np.float64), np.ones((4, 1))], axis=1)
    mapped = (inverse @ homo.T).T
    mapped = mapped[:, :2] / mapped[:, 2:3]
    return mapped.tolist()


def _identity_mesh(height: int, width: int) -> list:
    xs = np.linspace(0.0, width - 1.0, 4)
    ys = np.linspace(0.0, height - 1.0, 4)
    return [[float(x), float(y)] for y in ys for x in xs]


def test_remap_shapes_match_image():
    image = np.zeros((48, 64, 4), dtype=np.uint8)
    image[10:20, 15:30] = (20, 40, 60, 255)
    for kind in ("arc", "ring", "wave"):
        warped = warp_image(image, kind, bend=0.35)
        assert warped.shape == image.shape
        assert warped.dtype == np.uint8
        map_x, map_y = build_remap(kind, 48, 64, bend=0.35)
        assert map_x.shape == (48, 64)
        assert map_y.shape == (48, 64)
        assert map_x.dtype == np.float32
        assert map_y.dtype == np.float32

    rgb = _gradient(32, 40, channels=3)
    arc_rgb = warp_image(rgb, "arc", bend=0.0)
    assert arc_rgb.shape == (32, 40, 3)
    assert arc_rgb.dtype == np.uint8


def test_zero_bend_is_close_to_identity():
    image = _gradient(48, 64, channels=4)
    xs = np.arange(64, dtype=np.float32)[None, :]
    ys = np.arange(48, dtype=np.float32)[:, None]
    for kind in ("arc", "ring", "wave"):
        warped = warp_image(image, kind, bend=0.0)
        diff = np.abs(warped.astype(np.int16) - image.astype(np.int16))
        assert int(diff.max()) <= 2
        assert float(diff.mean()) < 1.0
        assert warped[24, 32, 0] == image[24, 32, 0]
        map_x, map_y = build_remap(kind, 48, 64, bend=0.0)
        assert float(np.max(np.abs(map_x - xs))) < 1e-3
        assert float(np.max(np.abs(map_y - ys))) < 1e-3


def test_perspective_quad_roundtrip():
    """quad — точки назначения TL, TR, BR, BL для углов прямоугольника кадра.

    Обратный quad — углы прямоугольника, прогнанные через inv(M),
    где M переводит прямоугольник в прямой quad.
    """
    height, width = 80, 100
    image = _marker_image(height, width)
    quad = [
        [22.0, 20.0],
        [70.0, 10.0],
        [90.0, 58.0],
        [15.0, 68.0],
    ]
    forward = warp_image(image, "perspective", quad=quad)
    assert forward.shape == image.shape
    assert forward.dtype == np.uint8
    origin = _centroid(image[:, :, 0])
    moved = _centroid(forward[:, :, 0])
    move = ((moved[0] - origin[0]) ** 2 + (moved[1] - origin[1]) ** 2) ** 0.5
    assert move > 4.0

    back = warp_image(forward, "perspective", quad=_inverse_destination_quad(height, width, quad))
    restored = _centroid(back[:, :, 0])
    error = ((restored[0] - origin[0]) ** 2 + (restored[1] - origin[1]) ** 2) ** 0.5
    assert error <= 3.0


def test_mesh_identity_grid_is_close_to_identity():
    image = _gradient(48, 64, channels=4)
    mesh = _identity_mesh(48, 64)
    warped = warp_image(image, "mesh", mesh=mesh)
    assert warped.shape == image.shape
    assert warped.dtype == np.uint8
    diff = np.abs(warped.astype(np.int16) - image.astype(np.int16))
    assert int(diff.max()) <= 8
    assert float(diff.mean()) < 1.0


def test_kind_none_and_unknown_return_equal_array():
    image = _gradient(24, 30, channels=4)
    for kind in ("none", "unknown", "NOPE"):
        warped = warp_image(image, kind, bend=0.7)
        assert np.array_equal(warped, image)
        assert warped is not image


def test_remap_maps_are_finite():
    for kind in ("arc", "ring", "wave"):
        map_x, map_y = build_remap(kind, 48, 64, bend=0.5)
        assert np.isfinite(map_x).all()
        assert np.isfinite(map_y).all()
        warped = warp_image(_gradient(48, 64), kind, bend=0.5)
        assert warped.dtype == np.uint8
        assert np.isfinite(warped).all()
        assert not np.array_equal(warped, _gradient(48, 64))


def test_invalid_quad_returns_unchanged():
    image = _marker_image()
    for quad in (
        None,
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
        [[0.0, 0.0], [float("nan"), 0.0], [10.0, 10.0], [0.0, 10.0]],
    ):
        warped = warp_image(image, "perspective", quad=quad)
        assert np.array_equal(warped, image)
        assert warped is not image


def test_invalid_or_tiny_inputs_stay_unchanged():
    image = _marker_image()
    assert np.array_equal(warp_image(image, "mesh", mesh=None), image)
    assert np.array_equal(warp_image(image, "mesh", mesh=[[0.0, 0.0], [1.0, 1.0]]), image)

    tiny = np.zeros((1, 8, 4), dtype=np.uint8)
    tiny[0, 3] = 9
    assert np.array_equal(warp_image(tiny, "arc", bend=0.8), tiny)

    empty = np.zeros((0, 4, 4), dtype=np.uint8)
    assert warp_image(empty, "wave", bend=1.0).shape == empty.shape
