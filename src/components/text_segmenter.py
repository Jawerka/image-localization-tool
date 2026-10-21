"""Пиксельная маска букв и оценка стиля внутри региона."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from src.components.bubble_contour import bubble_interior_mask
from src.models import MaskStroke, TextRegion
from src.utils.mask_metrics import otsu_threshold

# Отступ маски от контура чернил для SFX и free без баллона.
_INK_PAD_PX = 4
# Фиксированный inset силуэта (см. Config.bubble_mask_inset_px).
_DEFAULT_BUBBLE_INSET_PX = 2


def _line_heights(ink: np.ndarray) -> list[int]:
    rows = np.where(np.any(ink, axis=1))[0]
    if rows.size == 0:
        return []
    breaks = np.where(np.diff(rows) > 1)[0]
    starts = np.r_[rows[0], rows[breaks + 1]]
    ends = np.r_[rows[breaks], rows[-1]]
    return [int(end - start + 1) for start, end in zip(starts, ends)]


def _drop_border_components(binary: np.ndarray) -> np.ndarray:
    """Убрать контур баллона: компоненты, которые в основном лежат на краю кропа."""
    num, labels = cv2.connectedComponents((binary > 0).astype(np.uint8))
    if num <= 1:
        return binary
    height, width = binary.shape
    band = max(2, min(height, width) // 40)
    border = np.zeros_like(binary, dtype=bool)
    border[:band, :] = True
    border[-band:, :] = True
    border[:, :band] = True
    border[:, -band:] = True
    kept = np.zeros_like(binary)
    for label_id in range(1, num):
        component = labels == label_id
        area = int(np.sum(component))
        if area < 2:
            continue
        on_border = int(np.sum(component & border))
        if on_border / area > 0.45:
            continue
        kept[component] = 255
    return kept


def _alignment(ink: np.ndarray) -> str:
    cols = np.where(np.any(ink, axis=0))[0]
    if cols.size == 0:
        return "center"
    width = ink.shape[1]
    left = int(cols[0])
    right = width - 1 - int(cols[-1])
    if abs(left - right) <= width * 0.12:
        return "center"
    return "left" if left < right else "right"


def _is_uppercase(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    return sum(char.isupper() for char in letters) / len(letters) >= 0.8


def _background_color(image_rgb: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Цвет фона по кольцу вокруг бокса, а не по медиане самого текста."""
    height, width = image_rgb.shape[:2]
    pad = 8
    xa, ya = max(0, x0 - pad), max(0, y0 - pad)
    xb, yb = min(width, x1 + pad), min(height, y1 + pad)
    outer = image_rgb[ya:yb, xa:xb]
    ring = np.ones(outer.shape[:2], dtype=bool)
    ix0, iy0 = x0 - xa, y0 - ya
    ix1, iy1 = min(outer.shape[1], x1 - xa), min(outer.shape[0], y1 - ya)
    ring[iy0:iy1, ix0:ix1] = False
    pixels = outer[ring]
    if pixels.shape[0] < 12:
        pixels = outer.reshape(-1, 3)
    return np.median(pixels, axis=0)


def _snap_fill(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Серый от JPEG приводим к чёрному или белому. Цветной текст оставляем."""
    red, green, blue = color
    spread = max(red, green, blue) - min(red, green, blue)
    if spread >= 28:
        return color
    if max(red, green, blue) < 150:
        return (0, 0, 0)
    if min(red, green, blue) > 105:
        return (255, 255, 255)
    return color


def _on_fill_background_segment(
    color: tuple[int, int, int],
    fill: tuple[int, int, int],
    background: np.ndarray,
) -> bool:
    """Серый край сглаживания лежит на отрезке между заливкой и фоном."""
    point = np.array(color, dtype=np.float32)
    start = np.array(fill, dtype=np.float32)
    end = np.asarray(background, dtype=np.float32)
    delta = end - start
    length2 = float(np.dot(delta, delta))
    if length2 < 1.0:
        return True
    t = float(np.dot(point - start, delta) / length2)
    if t < -0.08 or t > 1.08:
        return False
    t_clamped = min(1.0, max(0.0, t))
    projection = start + t_clamped * delta
    return float(np.linalg.norm(point - projection)) <= 22.0


def _colors(crop: np.ndarray, ink: np.ndarray, background: np.ndarray) -> tuple[tuple[int, int, int], tuple[int, int, int] | None]:
    pixels = crop[ink]
    if pixels.size == 0:
        return (0, 0, 0), None
    distance = np.linalg.norm(pixels.astype(np.float32) - background, axis=1)
    cutoff = float(np.percentile(distance, 80))
    chosen = pixels[distance >= cutoff]
    if chosen.size == 0:
        chosen = pixels
    fill = _snap_fill(tuple(int(v) for v in np.median(chosen, axis=0)))
    kernel = np.ones((3, 3), np.uint8)
    ring = cv2.dilate(ink.astype(np.uint8), kernel, iterations=1) > 0
    ring = ring & ~ink
    ring_pixels = crop[ring]
    if ring_pixels.shape[0] < 20:
        return fill, None
    distance = np.linalg.norm(ring_pixels.astype(np.float32) - background, axis=1)
    stroke_pixels = ring_pixels[distance > 35]
    if stroke_pixels.shape[0] < 20:
        return fill, None
    stroke = tuple(int(v) for v in np.median(stroke_pixels, axis=0))
    if np.linalg.norm(np.array(stroke, dtype=np.float32) - np.array(fill, dtype=np.float32)) < 40:
        return fill, None
    if _on_fill_background_segment(stroke, fill, background):
        return fill, None
    return fill, stroke


def _bubble_retouch_mask(
    image_rgb: np.ndarray,
    region: TextRegion,
    *,
    inset_px: int = _DEFAULT_BUBBLE_INSET_PX,
) -> np.ndarray | None:
    """Маска ретуши диалога по силуэту облачка. Без баллона / SFX — None.

    При провале силуэта — None (вызывающий код останется на ink-маске),
    без эллипса по AABB детектора.
    """
    if region.document or region.bubble_bbox is None or region.block_type == "sfx":
        return None
    silhouette = bubble_interior_mask(image_rgb, region, inset_px=max(0, int(inset_px)))
    if np.any(silhouette):
        return silhouette
    return None


def segment_region(
    image_rgb: np.ndarray,
    region: TextRegion,
    capture_ink: dict[int, np.ndarray] | None = None,
    *,
    bubble_inset_px: int = _DEFAULT_BUBBLE_INSET_PX,
) -> np.ndarray:
    """Маска региона в координатах всей страницы. Обновляет цвета и кегль стиля.

    Диалог с баллоном — силуэт интерьера (фиксированный inset). Звук и free — ink.
    При провале силуэта диалог тоже идёт по ink. Без эллипса AABB.
    ``capture_ink`` пишет маску чернил до дилатации по id региона.
    """
    height, width = image_rgb.shape[:2]
    bubble = _bubble_retouch_mask(image_rgb, region, inset_px=bubble_inset_px)
    full = np.zeros((height, width), dtype=np.uint8)
    x, y, box_w, box_h = region.bbox
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + box_w)
    y1 = min(height, y + box_h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return bubble if bubble is not None else full

    pad = 3
    height, width = image_rgb.shape[:2]
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(width, x1 + pad), min(height, y1 + pad)
    crop = image_rgb[cy0:cy1, cx0:cx1]
    background = _background_color(image_rgb, x0, y0, x1, y1)
    distance = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    dist_u8 = np.clip(distance, 0, 255).astype(np.uint8)
    threshold = max(otsu_threshold(dist_u8), 28)
    binary = np.where(dist_u8 >= threshold, 255, 0).astype(np.uint8)
    binary = _drop_border_components(binary)

    ink_bool = binary > 0
    heights = _line_heights(ink_bool)
    line_height = int(np.median(heights)) if heights else max(8, box_h)
    # SFX и free без баллона: маска по контуру чернил +4px, без жирного пятна.
    tight_ink = region.block_type == "sfx" or region.bubble_bbox is None
    if tight_ink:
        radius = _INK_PAD_PX
    else:
        radius = max(2, int(round(line_height * 0.22)))
    kernel_size = radius * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    dilated = cv2.dilate(binary, kernel, iterations=1)

    fill, stroke = _colors(crop, ink_bool, background)
    style = region.style
    style.fill_rgb = fill
    style.stroke_rgb = stroke
    style.font_size = max(10, int(line_height * 0.85))
    if not (region.document and (region.manual or region.edited)):
        style.alignment = "left" if region.document else _alignment(ink_bool)
    style.uppercase = _is_uppercase(region.text)
    style.line_height = line_height
    if capture_ink is not None:
        ink = np.zeros((height, width), dtype=np.uint8)
        ink[cy0:cy1, cx0:cx1] = binary
        capture_ink[int(region.id)] = ink
    if bubble is not None:
        return bubble
    full[cy0:cy1, cx0:cx1] = dilated
    if region.document:
        # Соседние строки и аватары за рамкой документа не ретушируем.
        bounded = np.zeros_like(full)
        bounded[y0:y1, x0:x1] = full[y0:y1, x0:x1]
        return bounded
    return full


def apply_strokes(
    mask: np.ndarray,
    strokes: list[MaskStroke],
    image: Image.Image | None = None,
) -> np.ndarray:
    """Наложить штрихи кисти, ластика и заливку лассо. Входная маска не меняется.

    ``image`` — исходная страница для заливки по цвету (flood/erase_flood).
    """
    result = np.array(mask, copy=True)
    if not strokes:
        return result
    for stroke in strokes:
        points = [(int(point[0]), int(point[1])) for point in stroke.points]
        if not points:
            continue
        if stroke.mode in ("flood", "erase_flood"):
            if image is None:
                continue
            from src.components.flood_fill import flood_region, paint_region

            paint_region(result, flood_region(image, points[0], stroke.tolerance), stroke.mode)
            continue
        if stroke.mode in ("fill", "erase_fill"):
            if len(points) >= 3:
                contour = np.asarray(points, dtype=np.int32).reshape((-1, 1, 2))
                color = 0 if stroke.mode == "erase_fill" else 255
                cv2.fillPoly(result, [contour], color, lineType=cv2.LINE_8)
            continue
        radius = int(stroke.radius)
        if radius <= 0:
            continue
        color = 255 if stroke.mode == "paint" else 0
        thickness = max(1, radius * 2)
        if len(points) == 1:
            cv2.circle(result, points[0], radius, color, thickness=-1, lineType=cv2.LINE_8)
            continue
        for start, end in zip(points, points[1:]):
            cv2.line(result, start, end, color, thickness=thickness, lineType=cv2.LINE_8)
        for point in points:
            cv2.circle(result, point, radius, color, thickness=-1, lineType=cv2.LINE_8)
    return result


def segment_regions(
    image: Image.Image,
    regions: list[TextRegion],
    capture_ink: dict[int, np.ndarray] | None = None,
    *,
    bubble_inset_px: int = _DEFAULT_BUBBLE_INSET_PX,
) -> np.ndarray:
    """Общая маска букв для списка регионов.

    ``capture_ink`` — необязательный словарь id → маска чернил до дилатации.
    """
    rgb = np.array(image.convert("RGB"))
    if not regions:
        return np.zeros(rgb.shape[:2], dtype=np.uint8)
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for region in regions:
        part = segment_region(
            rgb,
            region,
            capture_ink=capture_ink,
            bubble_inset_px=bubble_inset_px,
        )
        mask = np.maximum(mask, part)
    return mask
