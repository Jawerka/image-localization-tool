"""Консервативная карта пространства для экспериментального расширения текста."""
from __future__ import annotations

import cv2
import numpy as np

BLOCKED, UNKNOWN, FREE = 0, 127, 255


def placement_space(image, source_field, *, source_ink=None, trusted_field=None, protected=None, gap_px=2):
    """Классифицировать исходные пиксели, не принимая гладкость за безопасность.

    Доверенный контур задаёт предел: это найденное облачко или известное
    поле документа, а не результат ретуши. Без него новые пиксели не получают
    разрешения. source_field — уже одобренное поле исходной надписи.
    """
    rgb = np.asarray(image.convert('RGB') if hasattr(image, 'convert') else image)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Нужно RGB-изображение')
    shape = rgb.shape[:2]
    masks = [source_field, source_ink, trusted_field, protected]
    if any(m is not None and np.asarray(m).shape != shape for m in masks):
        raise ValueError('Все маски должны совпадать с размером изображения')
    source = np.asarray(source_field) > 0
    trust = np.zeros(shape, bool) if trusted_field is None else np.asarray(trusted_field) > 0
    ink = np.zeros(shape, bool) if source_ink is None else np.asarray(source_ink) > 0
    hard = np.zeros(shape, np.uint8) if protected is None else (np.asarray(protected) > 0).astype(np.uint8)
    gap = max(1, min(32, round(gap_px)))
    hard = cv2.dilate(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap*2+1, gap*2+1))) > 0
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    blur = cv2.GaussianBlur(lab, (5, 5), 0)
    variance = np.maximum(0, cv2.GaussianBlur(lab*lab, (5, 5), 0)-blur*blur).mean(axis=2)
    dx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    edges = np.max(np.hypot(dx, dy), axis=2) > 100
    edges = cv2.dilate(edges.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    excluded_ink = cv2.dilate(ink.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    domain = np.ones(shape, bool) if trusted_field is None else trust
    samples = source & domain & ~excluded_ink & ~hard & ~edges
    state = np.full(shape, UNKNOWN, np.uint8)
    state[edges | hard] = BLOCKED
    # Собственное поле уже было разрешено до расширения; чужие запреты сильнее.
    state[source & domain & ~hard] = FREE
    metadata = dict(seed_pixels=int(samples.sum()), trusted=trusted_field is not None,
                    basis='исходное изображение; Lab, дисперсия, границы и доверенный контур')
    if samples.sum() >= 20 and trusted_field is not None:
        center = np.median(lab[samples], axis=0)
        deviation = np.linalg.norm(lab[samples]-center, axis=1)
        # Смешанный фон не служит надёжным цветовым образцом.
        spread = float(np.percentile(deviation, 80))
        metadata['seed_spread'] = round(spread, 3)
        if spread <= 18:
            distance = np.linalg.norm(lab-center, axis=2)
            clear = trust & (distance <= max(10., min(20., spread+8.))) & (variance <= 45) & ~edges & ~hard
            clear |= source & trust & ~hard
            _, labels = cv2.connectedComponents(clear.astype(np.uint8))
            ids = np.unique(labels[source & clear])
            ids = ids[ids != 0]
            if len(ids):
                state[np.isin(labels, ids)] = FREE
    state[hard] = BLOCKED
    metadata.update(free=int(np.sum(state == FREE)), blocked=int(np.sum(state == BLOCKED)),
                    unknown=int(np.sum(state == UNKNOWN)))
    return state, metadata
