"""Сборка регионов: привязка текста к баллону, абзацы, порядок чтения."""

from __future__ import annotations

import cv2
import numpy as np

from src.components.bubble_detector import Detection
from src.models import TextRegion
from src.utils.mask_metrics import otsu_threshold


def box_area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2]) * max(0, box[3])


def intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[0] + a[2], b[0] + b[2])
    y2 = min(a[1] + a[3], b[1] + b[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def overlap_ratio(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> float:
    """Доля площади inner, лежащая внутри outer."""
    area = box_area(inner)
    if area <= 0:
        return 0.0
    return intersection_area(inner, outer) / area


def center_inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    cx = inner[0] + inner[2] / 2
    cy = inner[1] + inner[3] / 2
    return outer[0] <= cx <= outer[0] + outer[2] and outer[1] <= cy <= outer[1] + outer[3]


def union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[0] + box[2] for box in boxes)
    y2 = max(box[1] + box[3] for box in boxes)
    return (x1, y1, x2 - x1, y2 - y1)


def vertical_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    """Зазор по вертикали. Отрицательный, если боксы пересекаются по Y."""
    a_bottom = a[1] + a[3]
    b_bottom = b[1] + b[3]
    if b[1] >= a_bottom:
        return b[1] - a_bottom
    if a[1] >= b_bottom:
        return a[1] - b_bottom
    return -1


def horizontal_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    x2 = min(a[0] + a[2], b[0] + b[2])
    overlap = max(0, x2 - x1)
    narrower = min(a[2], b[2])
    if narrower <= 0:
        return 0.0
    return overlap / narrower


def can_merge_paragraph(
    a: TextRegion,
    b: TextRegion,
    gap_ratio: float = 0.7,
) -> bool:
    """Строки одного абзаца: близко по вертикали, похожая высота, общее выравнивание."""
    if a.bubble_bbox is not None or b.bubble_bbox is not None:
        return False
    ha, hb = a.bbox[3], b.bbox[3]
    if min(ha, hb) <= 0:
        return False
    if max(ha, hb) / min(ha, hb) > 1.7:
        return False
    gap = vertical_gap(a.bbox, b.bbox)
    if gap > gap_ratio * min(ha, hb):
        return False
    left_delta = abs(a.bbox[0] - b.bbox[0])
    aligned = left_delta <= 0.25 * max(a.bbox[2], b.bbox[2])
    stacked = horizontal_overlap_ratio(a.bbox, b.bbox) >= 0.4
    return aligned or stacked


def can_merge_column(a: TextRegion, b: TextRegion) -> bool:
    """Куски одной колонки документа: общий левый край, узкий зазор, похожая ширина.

    Короткая последняя строка сливается с абзацем над ней. Заголовок с большим
    зазором и широкая строка под колонкой остаются отдельно.
    """
    if a.bubble_bbox is not None or b.bubble_bbox is not None:
        return False
    ha, hb = a.bbox[3], b.bbox[3]
    wa, wb = a.bbox[2], b.bbox[2]
    if min(ha, hb) <= 0 or min(wa, wb) <= 0:
        return False
    if max(wa, wb) / min(wa, wb) > 1.8:
        return False
    if vertical_gap(a.bbox, b.bbox) > max(20, int(0.35 * min(ha, hb))):
        return False
    aligned = abs(a.bbox[0] - b.bbox[0]) <= 0.2 * max(wa, wb)
    stacked = horizontal_overlap_ratio(a.bbox, b.bbox) >= 0.45
    return aligned or stacked


def merge_paragraphs(regions: list[TextRegion]) -> list[TextRegion]:
    """Слить соседние строки без баллона в абзацы."""
    return _merge_regions(regions, can_merge_paragraph)


def merge_columns(regions: list[TextRegion]) -> list[TextRegion]:
    """Собрать колонку документа из кусков, которые детектор разрезал по строкам."""
    return _merge_regions(regions, can_merge_column)


def _merge_regions(regions: list[TextRegion], can_merge) -> list[TextRegion]:
    if not regions:
        return []
    parent = list(range(len(regions)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(regions)):
        for j in range(i + 1, len(regions)):
            if can_merge(regions[i], regions[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for index in range(len(regions)):
        groups.setdefault(find(index), []).append(index)

    merged: list[TextRegion] = []
    for indexes in groups.values():
        members = [regions[index] for index in indexes]
        if len(members) == 1:
            merged.append(members[0])
            continue
        first = members[0]
        merged.append(TextRegion(
            id=first.id,
            bbox=union_box([item.bbox for item in members]),
            class_name=first.class_name,
            confidence=max(item.confidence for item in members),
            block_type=first.block_type,
            bubble_bbox=None,
        ))
    return merged


def _center_y(region: TextRegion) -> float:
    return region.bbox[1] + region.bbox[3] / 2


def assign_reading_order(regions: list[TextRegion], direction: str) -> list[TextRegion]:
    """Геометрический порядок: ряды по центру строки, внутри ряда ltr или rtl.

    Сравнение только с верхним боксом ряда, иначе лёгкое пересечение
    высоких баллонов склеивает всю страницу в один ряд.
    """
    rows: list[list[TextRegion]] = []
    for region in sorted(regions, key=_center_y):
        cy = _center_y(region)
        placed = False
        for row in rows:
            anchor = min(row, key=_center_y)
            limit = 0.35 * max(region.bbox[3], anchor.bbox[3], 8)
            if abs(cy - _center_y(anchor)) <= limit:
                row.append(region)
                placed = True
                break
        if not placed:
            rows.append([region])

    ordered: list[TextRegion] = []
    right_to_left = direction == "rtl"
    for row in rows:
        row.sort(key=lambda item: item.bbox[0], reverse=right_to_left)
        ordered.extend(row)
    for index, region in enumerate(ordered):
        region.order = index
    return ordered


def filter_detections(
    detections: list[Detection],
    image_size: tuple[int, int],
) -> list[Detection]:
    """Убрать бокс на всю страницу и фрагменты внутри крупного абзаца."""
    width, height = image_size
    page_area = max(1, width * height)
    filtered: list[Detection] = []
    for detection in detections:
        limit = 0.45 if detection.class_name == "bubble" else 0.6
        if box_area(detection.bbox) > limit * page_area:
            continue
        filtered.append(detection)

    texts = [item for item in filtered if item.class_name != "bubble"]
    bubbles = [item for item in filtered if item.class_name == "bubble"]
    drop: set[int] = set()
    for index, outer in enumerate(texts):
        if box_area(outer.bbox) < 0.12 * page_area:
            continue
        inner_ids = []
        for other_index, inner in enumerate(texts):
            if index == other_index:
                continue
            if overlap_ratio(inner.bbox, outer.bbox) < 0.8:
                continue
            if box_area(outer.bbox) <= box_area(inner.bbox) * 1.5:
                continue
            inner_ids.append(other_index)
        if not inner_ids:
            continue
        inner_area = sum(box_area(texts[inner_index].bbox) for inner_index in inner_ids)
        if inner_area >= 0.55 * box_area(outer.bbox):
            drop.add(index)
        else:
            drop.update(inner_ids)
    texts = [item for index, item in enumerate(texts) if index not in drop]
    return bubbles + texts


def _ink_components(crop: np.ndarray) -> np.ndarray:
    """Буквы в кропе. Крупные пятна (фото, заливка) отбрасываются."""
    if crop.size == 0:
        return np.zeros(crop.shape[:2], dtype=np.uint8)
    border = np.concatenate([
        crop[:2, :, :].reshape(-1, 3),
        crop[-2:, :, :].reshape(-1, 3),
        crop[:, :2, :].reshape(-1, 3),
        crop[:, -2:, :].reshape(-1, 3),
    ])
    background = np.median(border, axis=0) if border.size else np.array([255, 255, 255])
    distance = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    dist_u8 = np.clip(distance, 0, 255).astype(np.uint8)
    threshold = max(otsu_threshold(dist_u8), 28)
    binary = (dist_u8 >= threshold).astype(np.uint8)
    num, labels = cv2.connectedComponents(binary)
    kept = np.zeros_like(binary)
    crop_area = binary.shape[0] * binary.shape[1]
    for label_id in range(1, num):
        component = labels == label_id
        area = int(np.sum(component))
        if area < 8 or area > 0.02 * crop_area:
            continue
        ys, xs = np.where(component)
        box_area_px = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
        if box_area_px > 0.12 * crop_area:
            continue
        kept[component] = 1
    return kept


def _line_boxes(ink: np.ndarray) -> list[tuple[int, int, int, int]]:
    rows = np.where(np.any(ink, axis=1))[0]
    if rows.size == 0:
        return []
    breaks = np.where(np.diff(rows) > 2)[0]
    starts = np.r_[rows[0], rows[breaks + 1]]
    ends = np.r_[rows[breaks], rows[-1]]
    boxes = []
    for start, end in zip(starts, ends):
        band = ink[int(start):int(end) + 1]
        cols = np.where(np.any(band, axis=0))[0]
        if cols.size == 0:
            continue
        x0, x1 = int(cols[0]), int(cols[-1]) + 1
        boxes.append((x0, int(start), x1 - x0, int(end) - int(start) + 1))
    return boxes


def _group_line_boxes(lines: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
    if not lines:
        return []
    heights = [line[3] for line in lines]
    typical = float(np.median(heights))
    groups: list[list[tuple[int, int, int, int]]] = [[lines[0]]]
    for line in lines[1:]:
        previous = groups[-1][-1]
        gap = line[1] - (previous[1] + previous[3])
        if gap > max(12, 1.15 * typical):
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


def _padded_box(
    boxes: list[tuple[int, int, int, int]],
    origin: tuple[int, int],
    image_size: tuple[int, int],
    pad: int = 8,
) -> tuple[int, int, int, int]:
    union = union_box(boxes)
    x = union[0] + origin[0] - pad
    y = union[1] + origin[1] - pad
    w = union[2] + pad * 2
    h = union[3] + pad * 2
    width, height = image_size
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + w)
    y1 = min(height, y + h)
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def _drop_contained_duplicates(regions: list[TextRegion]) -> list[TextRegion]:
    """Убрать узкий фрагмент строки, если та же строка уже есть целиком."""
    drop: set[int] = set()
    for index, region in enumerate(regions):
        for other_index, other in enumerate(regions):
            if index == other_index or other_index in drop:
                continue
            if abs(_center_y(region) - _center_y(other)) > 0.45 * max(region.bbox[3], other.bbox[3], 8):
                continue
            if overlap_ratio(region.bbox, other.bbox) >= 0.7 and box_area(other.bbox) > box_area(region.bbox):
                drop.add(index)
                break
    return [region for index, region in enumerate(regions) if index not in drop]


def refine_document_regions(
    image_rgb: np.ndarray,
    regions: list[TextRegion],
    reading_order: str = "ltr",
) -> list[TextRegion]:
    """Крупный текстовый бокс документа режется на абзацы по строкам букв."""
    height, width = image_rgb.shape[:2]
    page_area = height * width
    refined: list[TextRegion] = []
    for region in regions:
        if region.bubble_bbox is not None or box_area(region.bbox) < 0.12 * page_area:
            refined.append(region)
            continue
        x, y, box_w, box_h = region.bbox
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + box_w), min(height, y + box_h)
        crop = image_rgb[y0:y1, x0:x1]
        lines = _line_boxes(_ink_components(crop))
        groups = _group_line_boxes(lines)
        if len(groups) <= 1:
            if lines:
                region.bbox = _padded_box(lines, (x0, y0), (width, height))
            refined.append(region)
            continue
        for group in groups:
            refined.append(TextRegion(
                id=0,
                bbox=_padded_box(group, (x0, y0), (width, height)),
                class_name="text_free",
                confidence=region.confidence,
                block_type="narration",
            ))
    refined = _drop_contained_duplicates(refined)
    refined = merge_columns(refined)
    direction = "rtl" if reading_order == "rtl" else "ltr"
    refined = assign_reading_order(refined, direction)
    for index, region in enumerate(refined, start=1):
        region.id = index
    return refined


def build_regions(
    detections: list[Detection],
    reading_order: str = "ltr",
) -> list[TextRegion]:
    """Привязать текст к баллону, слить абзацы и пронумеровать регионы.

    reading_order rtl/ltr задаёт только геометрический фолбэк.
    Порядок VLM, если он есть, подставляется позже.
    """
    bubbles = [item for item in detections if item.class_name == "bubble"]
    texts = [item for item in detections if item.class_name != "bubble"]
    grouped: dict[int, list[Detection]] = {index: [] for index in range(len(bubbles))}
    loose: list[Detection] = []

    for text in texts:
        best_index = None
        best_score = 0.0
        for index, bubble in enumerate(bubbles):
            inside = center_inside(text.bbox, bubble.bbox)
            covered = overlap_ratio(text.bbox, bubble.bbox)
            if not inside and covered < 0.5:
                continue
            score = covered + (1.0 if inside else 0.0)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None:
            loose.append(text)
        else:
            grouped[best_index].append(text)

    regions: list[TextRegion] = []
    for index, bubble in enumerate(bubbles):
        members = grouped[index]
        if not members:
            continue
        regions.append(TextRegion(
            id=0,
            bbox=union_box([item.bbox for item in members]),
            class_name="text_bubble",
            confidence=max(item.confidence for item in members),
            block_type="dialogue",
            bubble_bbox=bubble.bbox,
        ))

    for text in loose:
        regions.append(TextRegion(
            id=0,
            bbox=text.bbox,
            class_name=text.class_name,
            confidence=text.confidence,
            block_type="narration",
        ))

    regions = merge_paragraphs(regions)
    direction = "rtl" if reading_order == "rtl" else "ltr"
    regions = assign_reading_order(regions, direction)
    for index, region in enumerate(regions, start=1):
        region.id = index
    return regions
