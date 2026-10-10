"""Силуэт баллона: нет уголочков AABB снаружи, покрытие у обводки внутри."""

from __future__ import annotations

import cv2
import numpy as np

from src.components.bubble_contour import bubble_interior_mask
from src.components.text_segmenter import segment_region
from src.models import TextRegion, TextStyle


def _oval_page(
    size: int = 200,
    *,
    box: tuple[int, int, int, int] = (20, 20, 160, 160),
    ellipse_axes: tuple[int, int] = (55, 40),
) -> tuple[np.ndarray, TextRegion, np.ndarray]:
    """Белый овал с чёрной обводкой внутри широкого AABB; тёмный текст в центре."""
    image = np.full((size, size, 3), 230, dtype=np.uint8)
    bx, by, bw, bh = box
    cx, cy = bx + bw // 2, by + bh // 2
    cv2.ellipse(image, (cx, cy), ellipse_axes, 0, 0, 360, (255, 255, 255), thickness=-1)
    cv2.ellipse(image, (cx, cy), ellipse_axes, 0, 0, 360, (10, 10, 10), thickness=3)
    cv2.putText(image, "Hi", (cx - 18, cy + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

    oval = np.zeros((size, size), dtype=np.uint8)
    cv2.ellipse(oval, (cx, cy), ellipse_axes, 0, 0, 360, 255, thickness=-1)

    region = TextRegion(
        id=1,
        bbox=(cx - 22, cy - 16, 44, 32),
        text="Hi",
        bubble_bbox=box,
        block_type="dialogue",
        style=TextStyle(),
    )
    return image, region, oval


def _aabb_corner_patches(
    box: tuple[int, int, int, int],
    oval: np.ndarray,
    patch: int = 12,
) -> np.ndarray:
    """Маска четырёх углов AABB минус овал."""
    bx, by, bw, bh = box
    h, w = oval.shape
    corners = np.zeros_like(oval)
    coords = [
        (bx, by),
        (bx + bw - patch, by),
        (bx, by + bh - patch),
        (bx + bw - patch, by + bh - patch),
    ]
    for x, y in coords:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + patch), min(h, y + patch)
        corners[y0:y1, x0:x1] = 255
    return np.where((corners > 0) & (oval == 0), 255, 0).astype(np.uint8)


def test_no_aabb_corner_pixels():
    image, region, oval = _oval_page()
    mask = bubble_interior_mask(image, region, inset_px=2)
    assert np.any(mask), "ожидался силуэт интерьера"
    corners = _aabb_corner_patches(region.bubble_bbox, oval)
    leak = int(np.sum((mask > 0) & (corners > 0)))
    assert leak == 0, f"маска залезла в углы AABB снаружи овала: {leak} px"


def test_inner_coverage_near_outline():
    image, region, oval = _oval_page()
    mask = bubble_interior_mask(image, region, inset_px=2)
    assert np.any(mask)

    ker5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    ker8 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    inner = cv2.erode(oval, ker5)
    deeper = cv2.erode(oval, ker8)
    band = (inner > 0) & (deeper == 0)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    light_band = band & (gray > 200)
    total = int(np.sum(light_band))
    assert total > 50
    covered = int(np.sum(light_band & (mask > 0)))
    ratio = covered / total
    assert ratio >= 0.55, f"кольцо у обводки слабо покрыто: {ratio:.2f}"


def test_segment_dialogue_uses_silhouette_not_ellipse_fallback():
    image, region, oval = _oval_page()
    mask = segment_region(image, region, bubble_inset_px=2)
    assert np.any(mask)
    corners = _aabb_corner_patches(region.bubble_bbox, oval)
    assert int(np.sum((mask > 0) & (corners > 0))) == 0


def test_sfx_stays_ink_path():
    image, region, _oval = _oval_page()
    region.block_type = "sfx"
    region.bubble_bbox = None
    mask = segment_region(image, region, bubble_inset_px=2)
    assert np.any(mask)
    oval_fill = int(np.sum(mask > 0))
    assert oval_fill < 2500
