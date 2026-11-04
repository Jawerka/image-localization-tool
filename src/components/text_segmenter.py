"""Пиксельная маска букв и оценка стиля внутри региона."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from src.components.bubble_contour import balloon_flood_mask, bubble_interior_mask
from src.components.sfx_ink import drop_line_components, outlined_glyphs
from src.components.retouch_ink import confirmed_light_ink, smooth_light_mask
from src.models import MaskStroke, TextRegion
from src.utils.mask_metrics import otsu_threshold

# Отступ маски от контура чернил для SFX и free без баллона.
_INK_PAD_PX = 4
# Фиксированный inset силуэта (см. Config.bubble_mask_inset_px).
_DEFAULT_BUBBLE_INSET_PX = 2


def _outlined_text_mask(crop: np.ndarray) -> np.ndarray | None:
    """Замкнутая светлая обводка с тёмными буквами внутри, без фона облачка."""
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    light = ((np.min(crop, axis=2) >= 230)
             & (np.ptp(crop, axis=2) < 35)).astype(np.uint8)
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = np.zeros_like(gray)
    letters = 0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        # Фон, открытый на границе кропа, нельзя принимать за обводку.
        if x == 0 or y == 0 or x + w == crop.shape[1] or y + h == crop.shape[0]:
            continue
        filled = np.zeros_like(gray)
        cv2.drawContours(filled, [contour], -1, 255, -1)
        area = int(np.count_nonzero(filled))
        dark = (filled > 0) & (gray < 150)
        count = int(np.count_nonzero(dark))
        if area < 12 or not 0.08 <= count / area <= 0.75:
            continue
        n, _, stats, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8))
        heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n)
                   if stats[i, cv2.CC_STAT_AREA] >= 5]
        if not heights:
            continue
        # Широкое светлое поле с буквами внутри — облачко, а не ореол.
        thickness = cv2.distanceTransform(
            ((filled > 0) & (light > 0)).astype(np.uint8), cv2.DIST_L2, 5,
        )
        if float(thickness.max()) > max(2.0, float(np.median(heights)) * 0.5):
            continue
        letters += len(heights)
        result = np.maximum(result, filled)
    return result if letters >= 3 else None


def _line_heights(ink: np.ndarray) -> list[int]:
    rows = np.where(np.any(ink, axis=1))[0]
    if rows.size == 0:
        return []
    breaks = np.where(np.diff(rows) > 1)[0]
    starts = np.r_[rows[0], rows[breaks + 1]]
    ends = np.r_[rows[breaks], rows[-1]]
    return [int(end - start + 1) for start, end in zip(starts, ends)]


def _drop_non_letter_components(binary: np.ndarray) -> np.ndarray:
    """Убрать крупные пятна фона, которые не похожи на буквы."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8))
    if count <= 1:
        return binary
    height, width = binary.shape
    candidates = [
        stats[i, cv2.CC_STAT_HEIGHT]
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= 6
        and stats[i, cv2.CC_STAT_HEIGHT] > 3
        and stats[i, cv2.CC_STAT_WIDTH] < width * 0.4
        and stats[i, cv2.CC_STAT_HEIGHT] < height * 0.7
    ]
    if len(candidates) < 3:
        return binary
    typical = float(np.percentile(candidates, 60))
    kept = [
        i for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= 3
        and stats[i, cv2.CC_STAT_HEIGHT] <= max(8, typical * 2.0)
        and stats[i, cv2.CC_STAT_WIDTH] <= max(12, typical * 3.0)
    ]
    filtered = np.isin(labels, kept).astype(np.uint8) * 255
    if int(np.count_nonzero(filtered)) > 20:
        return filtered
    return binary


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
    letter_grow_px: int = 0,
) -> np.ndarray:
    """Маска региона в координатах всей страницы. Обновляет цвета и кегль стиля.

    Замкнутая светлая обводка — маска букв вместе с ореолом. Иначе диалог
    с баллоном — силуэт интерьера (фиксированный inset). Звук и free — ink.
    При провале силуэта диалог идёт по ink, а если собрался flood баллона — только внутри него.
    Без эллипса AABB.
    ``letter_grow_px`` расширяет только ink-маску. ``capture_ink`` пишет чернила
    до дилатации по id региона.
    """
    height, width = image_rgb.shape[:2]
    region._retouch_smooth_background = False
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
    outlined = _outlined_text_mask(crop) if not region.document else None
    light_confirmed, inverse_outline = confirmed_light_ink(crop) if not region.document else (None, False)
    # Силуэт не собрался, но flood баллона есть: фон и чернила берём из него,
    # а не из кольца бокса, которое может лечь на тёмный рисунок снаружи.
    balloon = None
    if (
        bubble is None
        and region.bubble_bbox is not None
        and not region.document
        and region.block_type != "sfx"
    ):
        balloon = balloon_flood_mask(image_rgb, region)
    if balloon is not None:
        background = np.median(image_rgb[balloon > 0], axis=0)
    else:
        background = _background_color(image_rgb, x0, y0, x1, y1)
    distance = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    dist_u8 = np.clip(distance, 0, 255).astype(np.uint8)
    threshold = max(otsu_threshold(dist_u8), 28)
    binary = np.where(dist_u8 >= threshold, 255, 0).astype(np.uint8)
    if balloon is not None:
        binary[balloon[cy0:cy1, cx0:cx1] == 0] = 0
    binary = _drop_border_components(binary)
    # source_ink подменяет тип на sfx у любой надписи. Решение о звуке
    # принимается по исходному типу, чтобы диалог не пошёл по пути наклейки.
    origin = getattr(region, "_mask_as", region.block_type)
    has_bubble = getattr(region, "_mask_bubble", region.bubble_bbox is not None)
    # Только звук. Свободный текст и реплики остаются на прежнем пути:
    # иначе страницы вроде test-5 теряют обычные буквы.
    sfx_like = (not region.document) and origin == "sfx" and not has_bubble
    glyph_mask = outlined_glyphs(crop) if sfx_like else None
    if glyph_mask is not None:
        binary = glyph_mask
        region._outline_ink = True
        bubble = None
        balloon = None
    elif sfx_like:
        binary = drop_line_components(binary)
    # На светлом фоне ищем тёмные штрихи независимо от оттенка кольца.
    light_ink = None
    # У непривязанной реплики кольцо ROI может попасть на волосы/рисунок.
    # Подтверждённый светлый фон позволяет искать отдельные тёмные буквы,
    # но не даёт права заливать весь белый фон или захватывать линии края.
    unbound_dialogue = (not has_bubble and origin == "dialogue" and
                        np.percentile(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), 35) >= 225)
    if (not region.document and (outlined is not None or glyph_mask is not None or unbound_dialogue or
            (region.bubble_bbox is not None and region.block_type != "sfx"))):
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if float(np.percentile(gray, 60)) >= 180:
            cutoff = min(170, max(60, otsu_threshold(gray)))
            candidate = _drop_border_components((gray <= cutoff).astype(np.uint8) * 255)
            n, labels, stats, _ = cv2.connectedComponentsWithStats(candidate)
            kept = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 3
                    and stats[i, cv2.CC_STAT_LEFT] > 0
                    and stats[i, cv2.CC_STAT_TOP] > 0
                    and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < crop.shape[1]
                    and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < crop.shape[0]
                    and not (stats[i, cv2.CC_STAT_WIDTH] > crop.shape[1] * .8
                             and stats[i, cv2.CC_STAT_HEIGHT] > crop.shape[0] * .6)]
            if unbound_dialogue:
                # Крупные связные фрагменты рисунка не являются буквами.
                kept = [i for i in kept if stats[i, cv2.CC_STAT_HEIGHT] <= box_h * .65
                        and stats[i, cv2.CC_STAT_WIDTH] <= box_w * .65]
            if len(kept) >= 3:
                light_ink = np.isin(labels, kept).astype(np.uint8) * 255
    if glyph_mask is not None:
        # Обводка могла замкнуться только у части строк. Остальные тёмные
        # буквы на светлом фоне оставляем, линии рисунка — нет.
        if outlined is not None:
            binary = np.maximum(binary, outlined)
        if light_ink is not None:
            binary = np.maximum(binary, drop_line_components(light_ink))
    elif outlined is not None:
        # Подтверждённая обводка имеет приоритет над силуэтом и инверсией:
        # плотные строки на рисунке не должны превращаться в маску фона.
        binary = outlined
        # Обводка может быть замкнута только у части слов. Остальные буквы
        # на светлом фоне сохраняем и для ретуши, и для capture_ink.
        if light_ink is not None:
            binary = np.maximum(binary, light_ink)
        bubble = None
        balloon = None
    elif light_ink is not None:
        binary = light_ink
        bubble = None
        balloon = None
    elif balloon is None and region.bubble_bbox is not None and not region.document:
        if binary.size and float(np.mean(binary > 0)) > 0.4:
            binary = np.where(binary > 0, np.uint8(0), np.uint8(255))
            binary = _drop_border_components(binary)
        binary = _drop_non_letter_components(binary)

    plain_light = (light_confirmed is not None and not inverse_outline and origin == "dialogue"
                   and float(np.median(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY))) >= 120)
    if plain_light and outlined is None:
        # Белые буквы на цветном облачке задают и чернила, и размер отступа.
        # Добавление только после дилатации оставляло тонкий ореол букв,
        # когда прежняя тёмная маска давала высоту строки в один пиксель.
        binary = light_confirmed
        light_ink = None
        bubble = None
        balloon = None
    ink_bool = binary > 0
    # Дополнение чернил не должно связывать строки фрагментом рисунка
    # и раздувать отступ маски, уже оценённый по подтверждённому ореолу.
    heights = _line_heights(outlined > 0 if outlined is not None else ink_bool)
    line_height = int(np.median(heights)) if heights else max(8, box_h)
    if plain_light:
        n_light, _, light_stats, _ = cv2.connectedComponentsWithStats(light_confirmed)
        glyph_heights = [light_stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n_light)
                         if light_stats[i, cv2.CC_STAT_AREA] >= 8 and light_stats[i, cv2.CC_STAT_HEIGHT] >= 6]
        if glyph_heights:
            line_height = int(np.percentile(glyph_heights, 75))
    if light_ink is not None and outlined is None:
        # Фрагмент рамки может связать строки по вертикали. Кегль и отступ
        # оцениваем по компонентам букв, не по высоте всего связанного блока.
        glyph_heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in kept
                         if stats[i, cv2.CC_STAT_AREA] >= 8
                         and stats[i, cv2.CC_STAT_HEIGHT] >= 6]
        if glyph_heights:
            line_height = min(line_height, int(np.percentile(glyph_heights, 75)))
    # SFX и free: маска по контуру чернил +4px. Диалог с боксом облачка
    # даже без flood остаётся с отступом от кегля, чтобы не терять ореол.
    tight_ink = region.block_type == "sfx" or region.bubble_bbox is None
    grow = max(0, int(letter_grow_px))
    if tight_ink:
        radius = _INK_PAD_PX + grow
    else:
        radius = max(2, int(round(line_height * 0.22))) + grow
    retouch_ink = binary
    if plain_light:
        retouch_ink = smooth_light_mask(crop, binary)
        if not np.array_equal(retouch_ink, binary):
            # Оболочка уже скрыла межбуквенный ореол. Большой отступ здесь
            # захватил бы край маленького цветного облачка.
            radius = 2 + grow
            region._retouch_smooth_background = True
    kernel_size = radius * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    dilated = cv2.dilate(retouch_ink, kernel, iterations=1)
    if balloon is not None:
        dilated[balloon[cy0:cy1, cx0:cx1] == 0] = 0

    fill, stroke = _colors(crop, ink_bool, background)
    style = region.style
    if not (region.manual or region.edited or region.layout_snapshot or region.auto_layout):
        style.fill_rgb = fill
        style.stroke_rgb = stroke
        style.font_size = max(10, int(line_height * 0.85))
        style.alignment = "left" if region.document else _alignment(ink_bool)
        style.uppercase = _is_uppercase(region.text)
        style.line_height = line_height
    if capture_ink is not None:
        ink = np.zeros((height, width), dtype=np.uint8)
        ink[cy0:cy1, cx0:cx1] = binary
        capture_ink[int(region.id)] = ink
    full[cy0:cy1, cx0:cx1] = dilated
    if bubble is not None:
        full = bubble
    if light_confirmed is not None and not sfx_like:
        # Дополняем прежний результат, не отменяя силуэт или найденные
        # тёмные буквы. Иначе просветы O/B могли бы сократить старую маску.
        addition = cv2.dilate(light_confirmed, kernel, iterations=1)
        full[cy0:cy1, cx0:cx1] = np.maximum(full[cy0:cy1, cx0:cx1], addition)
        region._retouch_preserve_background = True
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
    letter_grow_px: int = 0,
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
            letter_grow_px=letter_grow_px,
        )
        mask = np.maximum(mask, part)
    return mask
