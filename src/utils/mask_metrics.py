"""Метрики масок: покрытие чернил и выход за эталон.

IoU с прямоугольниками строк штрафует точную пиксельную маску.
Для очистки важнее, покрыт ли каждый штрих буквы и не задета ли картинка.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def load_perfect_mask_array(mask_path: str | Path) -> np.ndarray:
    """Загрузить эталонную маску с красными прямоугольниками."""
    img = Image.open(mask_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.array(img)
    red_mask = (
        (arr[:, :, 0] > 200)
        & (arr[:, :, 1] < 50)
        & (arr[:, :, 2] < 50)
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


def extract_ink_mask(image_rgb: np.ndarray, gt_mask: np.ndarray) -> np.ndarray:
    """Пиксели букв внутри эталонных прямоугольников.

    Фон оценивается по медиане прямоугольника, чернила — по расстоянию
    цвета и порогу Отсу. Возвращает uint8-маску того же размера.
    """
    if image_rgb.ndim != 3:
        raise ValueError("image_rgb must be HxWx3")
    gt = gt_mask > 0
    ink = np.zeros(gt.shape, dtype=np.uint8)
    if not np.any(gt):
        return ink

    num, labels = cv2.connectedComponents(gt.astype(np.uint8))
    for label_id in range(1, num):
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
        background = np.median(pixels, axis=0)
        distance = np.linalg.norm(crop - background, axis=2)
        dist_u8 = np.clip(distance, 0, 255).astype(np.uint8)
        threshold = max(otsu_threshold(dist_u8[roi]), 28)
        local = (dist_u8 >= threshold) & roi
        ink[y0:y1, x0:x1][local] = 255
    return ink


def ink_recall(predicted: np.ndarray, ink: np.ndarray) -> float:
    """Доля пикселей букв, которые покрыла предсказанная маска."""
    ink_px = ink > 0
    total = int(np.sum(ink_px))
    if total == 0:
        return 1.0
    hit = int(np.sum((predicted > 0) & ink_px))
    return hit / total


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
) -> dict[str, float]:
    """Остатки чернил после очистки и грязь в кольце 3 px вокруг букв.

    residue — доля пикселей букв, где очищенная картинка отличается от фона больше чем на 60.
    halo — доля кольца, где отличие от фона больше 20.
    Фон — медиана исходного кольца 3 px вокруг букв: прямоугольник эталона часто
    темнее самой бумаги, и белое кольцо иначе считается грязью.
    """
    if original.shape[:2] != cleaned.shape[:2] or original.shape[:2] != gt_mask.shape[:2]:
        raise ValueError("original, cleaned and gt_mask must share spatial shape")
    ink_mask = extract_ink_mask(original, gt_mask)
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
