"""Пиксельная маска букв и оценка стиля внутри региона."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from src.models import MaskStroke, TextRegion
from src.utils.mask_metrics import otsu_threshold


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


# Сжатие контура до ретуши. LaMa потом расширяет маску эллипсом 5×5, около 2px.
_BUBBLE_INSET_PX = 12


def _fill_contour(mask: np.ndarray) -> np.ndarray:
    """Залить дыры по внешнему контуру."""
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=-1)
    return filled


def _bubble_seed(image_rgb: np.ndarray, region: TextRegion) -> tuple[int, int] | None:
    """Пиксель цвета фона облачка ближе всего к центру текста, не буква."""
    if region.bubble_bbox is None:
        return None
    height, width = image_rgb.shape[:2]
    bx, by, bw, bh = region.bubble_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(width, bx + bw), min(height, by + bh)
    crop = image_rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    median = np.median(crop.reshape(-1, 3), axis=0)
    distance = np.linalg.norm(crop.astype(np.float32) - median, axis=2)
    close = distance <= 28
    if not np.any(close):
        close = distance <= float(np.percentile(distance, 40))
    ys, xs = np.where(close)
    cx = float(region.bbox[0] + region.bbox[2] / 2) - x0
    cy = float(region.bbox[1] + region.bbox[3] / 2) - y0
    nearest = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
    return int(xs[nearest] + x0), int(ys[nearest] + y0)


def _bubble_contour(image_rgb: np.ndarray, region: TextRegion) -> np.ndarray:
    """Заливка внутренности баллона. Пустая, если заливка не собрала треть бокса."""
    height, width = image_rgb.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    if region.bubble_bbox is None:
        return mask
    seed = _bubble_seed(image_rgb, region)
    if seed is None:
        return mask
    bx, by, bw, bh = region.bubble_bbox
    flood_mask = np.zeros((height + 2, width + 2), np.uint8)
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(
        bgr, flood_mask, seed, (255, 255, 255),
        (20, 20, 20), (20, 20, 20), flags,
    )
    filled = flood_mask[1:-1, 1:-1]
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(width, bx + bw), min(height, by + bh)
    mask[y0:y1, x0:x1] = filled[y0:y1, x0:x1]
    box_area = max(1, (x1 - x0) * (y1 - y0))
    if int(np.sum(mask > 0)) < 0.33 * box_area:
        return np.zeros((height, width), dtype=np.uint8)
    return _fill_contour(mask)


def _inset_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    """Сжать маску внутрь эллиптическим ядром."""
    if radius <= 0 or not np.any(mask):
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    return cv2.erode(mask, kernel, iterations=1)


def _inscribed_ellipse(
    shape: tuple[int, int],
    bubble_bbox: tuple[int, int, int, int],
    radius: int,
) -> np.ndarray:
    """Эллипс, вписанный в бокс баллона и уже отступленный от его краёв."""
    mask = np.zeros(shape, dtype=np.uint8)
    x, y, bw, bh = bubble_bbox
    axes = (max(1, int(bw / 2) - radius), max(1, int(bh / 2) - radius))
    center = (int(x + bw / 2), int(y + bh / 2))
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, thickness=-1)
    return mask


def _bubble_retouch_mask(image_rgb: np.ndarray, region: TextRegion) -> np.ndarray | None:
    """Маска ретуши диалога по контуру облачка. Для звука и текста без баллона — None."""
    if region.bubble_bbox is None or region.block_type == "sfx":
        return None
    contour = _bubble_contour(image_rgb, region)
    if np.any(contour):
        shrunk = _inset_mask(contour, _BUBBLE_INSET_PX)
        if np.any(shrunk):
            return shrunk
    return _inscribed_ellipse(image_rgb.shape[:2], region.bubble_bbox, _BUBBLE_INSET_PX)


def segment_region(
    image_rgb: np.ndarray,
    region: TextRegion,
    capture_ink: dict[int, np.ndarray] | None = None,
) -> np.ndarray:
    """Маска региона в координатах всей страницы. Обновляет цвета и кегль стиля.

    Диалог с баллоном закрашивает контур облачка, сжатый на ``_BUBBLE_INSET_PX``.
    Звук и текст без баллона остаются маской чернил.
    Остальные поля стиля (шрифт, поворот, дуга, режим обводки) сохраняются.
    ``capture_ink`` пишет маску чернил до дилатации по id региона.
    """
    height, width = image_rgb.shape[:2]
    bubble = _bubble_retouch_mask(image_rgb, region)
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
    radius = max(2, int(round(line_height * 0.22)))
    if region.block_type == "sfx":
        # Обводка звукоподражания шире диалога: штрих должен попасть в маску.
        radius = max(radius + 2, int(round(radius * 1.6)))
    kernel_size = radius * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    dilated = cv2.dilate(binary, kernel, iterations=1)

    fill, stroke = _colors(crop, ink_bool, background)
    style = region.style
    style.fill_rgb = fill
    style.stroke_rgb = stroke
    style.font_size = max(10, int(line_height * 0.85))
    style.alignment = _alignment(ink_bool)
    style.uppercase = _is_uppercase(region.text)
    style.line_height = line_height
    if capture_ink is not None:
        ink = np.zeros((height, width), dtype=np.uint8)
        ink[cy0:cy1, cx0:cx1] = binary
        capture_ink[int(region.id)] = ink
    if bubble is not None:
        return bubble
    full[cy0:cy1, cx0:cx1] = dilated
    return full


def apply_strokes(mask: np.ndarray, strokes: list[MaskStroke]) -> np.ndarray:
    """Наложить штрихи кисти и ластика. Входная маска не меняется."""
    result = np.array(mask, copy=True)
    if not strokes:
        return result
    for stroke in strokes:
        radius = int(stroke.radius)
        if radius <= 0 or not stroke.points:
            continue
        color = 255 if stroke.mode == "paint" else 0
        points = [(int(point[0]), int(point[1])) for point in stroke.points]
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
) -> np.ndarray:
    """Общая маска букв для списка регионов.

    ``capture_ink`` — необязательный словарь id → маска чернил до дилатации.
    """
    rgb = np.array(image.convert("RGB"))
    if not regions:
        return np.zeros(rgb.shape[:2], dtype=np.uint8)
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for region in regions:
        part = segment_region(rgb, region, capture_ink=capture_ink)
        mask = np.maximum(mask, part)
    return mask
