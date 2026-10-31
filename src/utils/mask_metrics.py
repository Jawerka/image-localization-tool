"""Метрики масок: покрытие чернил и выход за эталон.

IoU с прямоугольниками строк штрафует точную пиксельную маску.
Для очистки важнее, покрыт ли каждый штрих буквы и не задета ли картинка.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Ниже этого контраста к фону штрих не считается буквой.
_INK_FLOOR = 28
# Контраст выше шума, но ниже пола: буквы есть, метрика их не выделила.
_FAINT_FLOOR = 4


def load_perfect_mask_array(mask_path: str | Path) -> np.ndarray:
    """Загрузить эталонную маску с красными прямоугольниками.

    Полупрозрачные и полностью прозрачные пиксели не входят в эталон:
    разметка часто лежит в альфа-канале поверх чёрного холста.
    """
    img = Image.open(mask_path)
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    arr = np.array(img.convert("RGBA"))
    red_mask = (
        (arr[:, :, 0] > 200)
        & (arr[:, :, 1] < 50)
        & (arr[:, :, 2] < 50)
        & (arr[:, :, 3] >= 128)
    )
    return red_mask.astype(np.uint8) * 255


def otsu_threshold(values: np.ndarray) -> int:
    """Порог Отсу по одномерному массиву яркостей 0–255."""
    flat = values.astype(np.uint8).ravel()
    if flat.size == 0:
        return 127
    hist = np.bincount(flat, minlength=256).astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 127
    prob = hist / total
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    sigma = np.zeros(256, dtype=np.float64)
    valid = denom > 1e-9
    sigma[valid] = (mu_t * omega[valid] - mu[valid]) ** 2 / denom[valid]
    return int(np.argmax(sigma))


@dataclass
class InkExtraction:
    """Чернила внутри эталона и то, смогла ли метрика их выделить.

    ``measured`` — буквы выделены во всех компонентах.
    ``no_ink`` — в рамках нет контраста, букв действительно нет.
    ``undetermined`` — контраст есть, но он ниже пола и буквы не выделены.
    """

    mask: np.ndarray
    status: str
    ink_pixels: int
    components: int
    unseparated: int


def extract_ink(image_rgb: np.ndarray, gt_mask: np.ndarray) -> InkExtraction:
    """Пиксели букв внутри эталонных прямоугольников и статус выделения."""
    if image_rgb.ndim != 3:
        raise ValueError("image_rgb must be HxWx3")
    gt = gt_mask > 0
    ink = np.zeros(gt.shape, dtype=np.uint8)
    components = 0
    unseparated = 0
    if np.any(gt):
        _num, labels = cv2.connectedComponents(gt.astype(np.uint8))
        for label_id in range(1, _num):
            region = labels == label_id
            ys, xs = np.where(region)
            if ys.size < 8:
                continue
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            crop = image_rgb[y0:y1, x0:x1].astype(np.float32)
            roi = region[y0:y1, x0:x1]
            pixels = crop[roi]
            if pixels.size < 8:
                continue
            components += 1
            background = np.median(pixels, axis=0)
            distance = np.linalg.norm(crop - background, axis=2)
            dist_u8 = np.clip(distance, 0, 255).astype(np.uint8)
            raw_threshold = otsu_threshold(dist_u8[roi])
            threshold = max(raw_threshold, _INK_FLOOR)
            local = (dist_u8 >= threshold) & roi
            if np.any(local):
                ink[y0:y1, x0:x1][local] = 255
                continue
            faint = (dist_u8 >= _FAINT_FLOOR) & roi
            if raw_threshold < _INK_FLOOR and int(np.sum(faint)) >= 8:
                unseparated += 1
    ink_pixels = int(np.sum(ink > 0))
    if unseparated:
        status = "undetermined"
    elif ink_pixels:
        status = "measured"
    else:
        status = "no_ink"
    return InkExtraction(ink, status, ink_pixels, components, unseparated)


def extract_ink_mask(image_rgb: np.ndarray, gt_mask: np.ndarray) -> np.ndarray:
    """Пиксели букв внутри эталонных прямоугольников.

    Фон оценивается по медиане прямоугольника, чернила — по расстоянию
    цвета и порогу Отсу. Возвращает uint8-маску того же размера.
    """
    return extract_ink(image_rgb, gt_mask).mask


def ink_recall(predicted: np.ndarray, ink: np.ndarray) -> float:
    """Доля пикселей букв, которые покрыла предсказанная маска.

    Пустая маска чернил даёт 1.0 только как историческое значение.
    Для решения «измерено / букв нет / не удалось выделить» используйте
    ``ink_report``: пустой результат там не считается идеальным покрытием.
    """
    ink_px = ink > 0
    total = int(np.sum(ink_px))
    if total == 0:
        return 1.0
    hit = int(np.sum((predicted > 0) & ink_px))
    return hit / total


def ink_report(predicted: np.ndarray, extraction: InkExtraction) -> dict:
    """Покрытие букв вместе со статусом, а не голое 100 % при пустой выборке."""
    recall = None
    if extraction.ink_pixels:
        recall = ink_recall(predicted, extraction.mask)
    return {
        "status": extraction.status,
        "recall": recall,
        "ink_pixels": extraction.ink_pixels,
        "components": extraction.components,
        "unseparated": extraction.unseparated,
    }


def spill(predicted: np.ndarray, gt_mask: np.ndarray, margin: int = 6) -> float:
    """Доля маски за пределами эталона, расширенного на margin пикселей."""
    pred = predicted > 0
    total = int(np.sum(pred))
    if total == 0:
        return 0.0
    kernel_size = margin * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    allowed = cv2.dilate((gt_mask > 0).astype(np.uint8), kernel, iterations=1) > 0
    outside = int(np.sum(pred & ~allowed))
    return outside / total


def cleanup_residue(
    original: np.ndarray,
    cleaned: np.ndarray,
    gt_mask: np.ndarray,
    extraction: InkExtraction | None = None,
) -> dict:
    """Остатки чернил после очистки и грязь в кольце 3 px вокруг букв.

    residue — доля пикселей букв, где очищенная картинка отличается от фона больше чем на 60.
    halo — доля кольца, где отличие от фона больше 20.
    Фон — медиана исходного кольца 3 px вокруг букв: прямоугольник эталона часто
    темнее самой бумаги, и белое кольцо иначе считается грязью.
    """
    if original.shape[:2] != cleaned.shape[:2] or original.shape[:2] != gt_mask.shape[:2]:
        raise ValueError("original, cleaned and gt_mask must share spatial shape")
    extraction = extraction or extract_ink(original, gt_mask)
    ink_mask = extraction.mask
    residue_num = 0
    residue_den = 0
    halo_num = 0
    halo_den = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    labels_source = (gt_mask > 0).astype(np.uint8)
    component_count, labels = cv2.connectedComponents(labels_source)
    ink_all = ink_mask > 0
    for label_id in range(1, component_count):
        region = labels == label_id
        ink = ink_all & region
        if not np.any(ink):
            continue
        ring = (cv2.dilate(ink.astype(np.uint8), kernel, iterations=1) > 0) & ~ink_all
        if np.any(ring):
            background = np.median(original[ring].astype(np.float32), axis=0)
        else:
            background_pixels = original[region & ~ink]
            if background_pixels.shape[0] < 8:
                background_pixels = original[region]
            background = np.median(background_pixels.astype(np.float32), axis=0)
        cleaned_ink = cleaned[ink].astype(np.float32)
        residue_den += int(cleaned_ink.shape[0])
        residue_num += int(np.sum(np.linalg.norm(cleaned_ink - background, axis=1) > 60))
        if not np.any(ring):
            continue
        cleaned_ring = cleaned[ring].astype(np.float32)
        halo_den += int(cleaned_ring.shape[0])
        halo_num += int(np.sum(np.linalg.norm(cleaned_ring - background, axis=1) > 20))
    return {
        "residue": (residue_num / residue_den) if residue_den else 0.0,
        "halo": (halo_num / halo_den) if halo_den else 0.0,
        "status": extraction.status,
        "ink_pixels": extraction.ink_pixels,
        "components": extraction.components,
        "unseparated": extraction.unseparated,
    }


def allowed_cleanup_zone(
    line_mask: np.ndarray,
    balloon_mask: np.ndarray | None = None,
    margin: int = 6,
) -> np.ndarray:
    """Где очистке разрешено менять пиксели: строки с запасом и баллоны."""
    kernel_size = margin * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    zone = cv2.dilate((line_mask > 0).astype(np.uint8), kernel, iterations=1)
    if balloon_mask is not None:
        zone = np.maximum(zone, (balloon_mask > 0).astype(np.uint8))
    return zone * np.uint8(255)


def damage(
    original: np.ndarray,
    cleaned: np.ndarray,
    allowed: np.ndarray,
    threshold: int = 12,
) -> dict:
    """Доля пикселей вне разрешённой зоны, изменившихся сильнее порога.

    Порог сравнивает максимальный канал, а не среднее: один сдвинутый
    канал уже считается порчей рисунка.
    """
    if original.shape[:2] != cleaned.shape[:2] or original.shape[:2] != allowed.shape[:2]:
        raise ValueError("original, cleaned and allowed must share spatial shape")
    delta = np.max(
        np.abs(original.astype(np.int16) - cleaned.astype(np.int16)),
        axis=2,
    )
    outside = allowed == 0
    outside_pixels = int(np.sum(outside))
    damaged = int(np.sum((delta > threshold) & outside))
    return {
        "damage": (damaged / outside_pixels) if outside_pixels else 0.0,
        "damaged_pixels": damaged,
        "outside_pixels": outside_pixels,
    }


def box_metrics(predicted: np.ndarray, gt_mask: np.ndarray) -> dict[str, float]:
    """IoU, precision, recall и F1 по площадям масок."""
    pred = predicted > 0
    gt = gt_mask > 0
    intersection = float(np.sum(pred & gt))
    pred_area = float(np.sum(pred))
    gt_area = float(np.sum(gt))
    union = float(np.sum(pred | gt))
    iou = intersection / union if union else 0.0
    precision = intersection / pred_area if pred_area else 0.0
    recall = intersection / gt_area if gt_area else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"iou": iou, "precision": precision, "recall": recall, "f1": f1}
