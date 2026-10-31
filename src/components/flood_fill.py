"""Заливка по цвету исходной страницы (4-связная, ΔE76 в CIELAB)."""

from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
from PIL import Image

# ΔE76 0..100 на шкале толерантности; выше — уже другие цвета.
MAX_DELTA_E = 60.0


def flood_region(image: Image.Image, seed: tuple[int, int], tolerance: int) -> np.ndarray:
    """Маска пикселей, связанных с ``seed`` и близких к нему по цвету."""
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    x, y = int(seed[0]), int(seed[1])
    if not (0 <= x < width and 0 <= y < height):
        return np.zeros((height, width), dtype=bool)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.int16)
    delta = lab - lab[y, x]
    distance = np.sqrt(np.sum(delta.astype(np.float32) ** 2, axis=2))
    limit = max(0.0, min(100.0, float(tolerance))) / 100.0 * MAX_DELTA_E
    similar = (distance <= limit).astype(np.uint8)
    # floodFill меняет только similar; 4-связность — флаг 4, без диагоналей.
    scratch = np.zeros((height + 2, width + 2), dtype=np.uint8)
    cv2.floodFill(similar, scratch, (x, y), 2, flags=4)
    return similar == 2


def paint_region(mask: np.ndarray, region: np.ndarray, mode: str) -> None:
    """Записать регион в маску: flood → 255, erase_flood → 0. На месте."""
    height = min(mask.shape[0], region.shape[0])
    width = min(mask.shape[1], region.shape[1])
    mask[:height, :width][region[:height, :width]] = 0 if mode == "erase_flood" else 255


def fill_preview_png(
    image: Image.Image,
    seed: tuple[int, int],
    tolerance: int,
    mode: str,
) -> tuple[bytes, int, int]:
    """Полупрозрачный PNG региона и его смещение в координатах страницы."""
    region = flood_region(image, seed, tolerance)
    if not region.any():
        return b"", 0, 0
    ys, xs = np.nonzero(region)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    color = (255, 153, 153, 150) if mode == "erase_flood" else (144, 238, 144, 150)
    rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    rgba[region[y0:y1, x0:x1]] = color
    buffer = BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, format="PNG")
    return buffer.getvalue(), x0, y0
