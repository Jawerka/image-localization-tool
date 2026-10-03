"""Метрики покрытия чернил и выхода маски за эталон."""

import numpy as np

from src.utils.mask_metrics import cleanup_residue, extract_ink_mask, ink_recall, spill


def test_ink_recall_and_spill():
    image = np.full((40, 40, 3), 255, dtype=np.uint8)
    image[10:20, 10:20] = 0
    gt = np.zeros((40, 40), dtype=np.uint8)
    gt[5:25, 5:25] = 255
    ink = extract_ink_mask(image, gt)
    assert ink[15, 15] == 255
    assert ink[0, 0] == 0

    predicted = gt.copy()
    assert ink_recall(predicted, ink) == 1.0
    assert spill(predicted, gt) == 0.0

    small = np.zeros_like(gt)
    small[15:17, 15:17] = 255
    assert ink_recall(small, ink) < 1.0

    spilled = np.zeros_like(gt)
    spilled[0:4, 0:4] = 255
    assert spill(spilled, gt, margin=1) == 1.0


def test_cleanup_residue_is_zero_after_perfect_fill():
    original = np.full((40, 40, 3), 255, dtype=np.uint8)
    original[10:20, 10:20] = 0
    gt = np.zeros((40, 40), dtype=np.uint8)
    gt[5:25, 5:25] = 255
    cleaned = original.copy()
    cleaned[10:20, 10:20] = 255
    metrics = cleanup_residue(original, cleaned, gt)
    assert metrics["residue"] == 0.0
    assert metrics["halo"] == 0.0

    leftover = cleanup_residue(original, original, gt)
    assert leftover["residue"] > 0

    halo = cleaned.copy()
    halo[8:10, 10:20] = 220
    dirty_ring = cleanup_residue(original, halo, gt)
    assert dirty_ring["halo"] > 0
