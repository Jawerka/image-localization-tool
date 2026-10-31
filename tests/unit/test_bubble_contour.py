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
def test_two_tone_bubble_keeps_both_sides():
    import cv2
    import numpy as np
    from src.models import TextRegion
    from src.components.bubble_contour import bubble_interior_mask
    rgb = np.full((160, 260, 3), 65, np.uint8)
    inside = np.zeros((160, 260), np.uint8)
    cv2.ellipse(inside, (130, 80), (110, 65), 0, 0, 360, 255, -1)
    rgb[inside > 0] = (245, 240, 235)
    right = (inside > 0) & (np.indices(inside.shape)[1] > 130)
    rgb[right] = (218, 225, 235)
    cv2.putText(rgb, 'TEXT', (70, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (30,30,30), 3)
    region = TextRegion(1, (60, 45, 140, 65), bubble_bbox=(18, 13, 224, 134))
    mask = bubble_interior_mask(rgb, region)
    assert mask[60, 190] == 255
    assert mask[60, 70] == 255
    assert mask[15, 20] == 0


def test_translucent_bubble_with_white_halo_covers_letters():
    rgb = np.full((180, 240, 3), 40, np.uint8)
    yy, xx = np.indices((180, 240))
    rgb[:] = (40, 50, 55)
    cv2.ellipse(rgb, (120, 90), (95, 65), 0, 0, 360, (212, 212, 214), -1)
    rgb = np.clip(rgb.astype(np.int16) + (((xx + yy) % 12) - 6)[..., None], 0, 255).astype(np.uint8)
    cv2.putText(rgb, "HI", (78, 102), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (250, 250, 250), 8)
    cv2.putText(rgb, "HI", (78, 102), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (25, 25, 25), 2)
    oval = np.zeros(rgb.shape[:2], np.uint8)
    cv2.ellipse(oval, (120, 90), (95, 65), 0, 0, 360, 255, -1)
    letters = (oval > 0) & (np.linalg.norm(rgb.astype(np.float32) - np.array([25, 25, 25]), axis=2) < 40)
    region = TextRegion(1, (70, 55, 100, 70), bubble_bbox=(25, 25, 190, 130), text="HI")
    mask = segment_region(rgb, region)
    n_letters = int(np.count_nonzero(letters))
    covered = int(np.count_nonzero(letters & (mask > 0)))
    assert n_letters > 40
    assert covered / n_letters >= 0.99
    areas = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            shifted = TextRegion(
                1, (70 + dx, 55 + dy, 100, 70), bubble_bbox=(25, 25, 190, 130), text="HI",
            )
            part = segment_region(rgb, shifted)
            areas.append(int(np.count_nonzero(part)))
    mid = float(np.median(areas))
    assert mid > 0
    assert max(areas) / mid <= 1.05
    assert min(areas) / mid >= 0.95


def test_flood_rejects_gradient_tail_leak():
    from src.components.bubble_contour import balloon_flood_mask
    rgb = np.full((160, 220, 3), 20, np.uint8)
    cv2.ellipse(rgb, (90, 80), (55, 45), 0, 0, 360, (230, 230, 230), -1)
    for x in range(140, 210):
        t = (x - 140) / 70
        color = int(230 * (1 - t) + 20 * t)
        rgb[70:90, x] = (color, color, color)
    cv2.putText(rgb, "OK", (62, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    region = TextRegion(1, (50, 55, 80, 50), bubble_bbox=(30, 30, 120, 100), text="OK")
    flood = balloon_flood_mask(rgb, region)
    if flood is not None:
        assert int(np.count_nonzero(flood[:, 150:])) == 0
        assert int(np.count_nonzero(flood)) < 120 * 100 * 0.95


def test_tapered_top_does_not_mask_dark_corners():
    rgb = np.full((200, 180, 3), 30, np.uint8)
    pts = np.array([[40, 40], [140, 40], [165, 170], [15, 170]], np.int32)
    cv2.fillConvexPoly(rgb, pts, (220, 220, 220))
    cv2.putText(rgb, "TOP", (55, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
    cv2.putText(rgb, "TEXT", (45, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
    region = TextRegion(1, (20, 30, 140, 150), bubble_bbox=(10, 20, 160, 165), text="TOP TEXT")
    mask = segment_region(rgb, region)
    assert int(np.count_nonzero(mask[25:38, 15:35])) == 0
    assert int(np.count_nonzero(mask[25:38, 145:165])) == 0
    assert int(np.count_nonzero(mask[80:150, 40:140])) > 50


def test_caption_mislabelled_as_bubble_stays_on_letters():
    rgb = np.full((160, 220, 3), 35, np.uint8)
    rgb[:80] = (80, 40, 20)
    rgb[80:] = (20, 60, 70)
    cv2.putText(rgb, "ROOM", (50, 95), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (250, 250, 250), 8)
    cv2.putText(rgb, "ROOM", (50, 95), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2)
    letters = np.linalg.norm(rgb.astype(np.float32) - np.array([20, 20, 20]), axis=2) < 28
    letters[:70] = False
    letters[120:] = False
    region = TextRegion(1, (40, 55, 140, 55), bubble_bbox=(20, 30, 180, 100), text="ROOM")
    mask = segment_region(rgb, region)
    extra = int(np.count_nonzero((mask > 0) & ~cv2.dilate(letters.astype(np.uint8), np.ones((15, 15), np.uint8))))
    assert extra < 800
    assert int(np.count_nonzero(mask)) < 5000
    assert int(np.count_nonzero(letters & (mask > 0))) >= 80


def test_leak_around_open_outline_falls_back_instead_of_erasing_border():
    import cv2
    import numpy as np
    from src.models import TextRegion
    from src.components.bubble_contour import bubble_interior_mask
    rgb=np.full((180,240,3),245,np.uint8)
    cv2.rectangle(rgb,(20,20),(220,160),(25,25,25),4)
    rgb[15:26,90:130]=245
    cv2.putText(rgb,'TEST',(50,100),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    r=TextRegion(1,(50,65,140,45),bubble_bbox=(10,10,220,160))
    mask=bubble_interior_mask(rgb,r)
    assert not np.any(mask)
