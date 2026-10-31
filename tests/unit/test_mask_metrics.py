"""Метрики покрытия чернил и выхода маски за эталон."""

import numpy as np
from PIL import Image

from src.utils.mask_metrics import (
    cleanup_residue,
    damage,
    extract_ink,
    extract_ink_mask,
    ink_recall,
    ink_report,
    load_perfect_mask_array,
    spill,
)


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
    assert dirty_ring["status"] == "measured"


def test_transparent_red_is_not_ground_truth(tmp_path):
    canvas = np.zeros((20, 20, 4), dtype=np.uint8)
    canvas[2:8, 2:8] = (255, 0, 0, 0)
    canvas[10:18, 10:18] = (255, 0, 0, 255)
    path = tmp_path / "page-mask.png"
    Image.fromarray(canvas, "RGBA").save(path)
    mask = load_perfect_mask_array(path)
    assert mask[4, 4] == 0
    assert mask[14, 14] == 255


def test_faint_gray_text_is_undetermined():
    """245 на 255 не должен давать recall 100 % и нулевые остатки как успех."""
    image = np.full((48, 96, 3), 255, dtype=np.uint8)
    image[14:34, 16:72] = 245
    gt = np.zeros((48, 96), dtype=np.uint8)
    gt[8:40, 8:84] = 255
    extraction = extract_ink(image, gt)
    assert extraction.status == "undetermined"
    assert extraction.unseparated == 1
    assert extraction.ink_pixels == 0
    assert ink_report(np.zeros_like(gt), extraction)["recall"] is None
    residue = cleanup_residue(image, image, gt, extraction)
    assert residue["status"] == "undetermined"
    assert residue["ink_pixels"] == 0


def test_blank_rectangle_has_no_ink():
    image = np.full((40, 40, 3), 255, dtype=np.uint8)
    gt = np.zeros((40, 40), dtype=np.uint8)
    gt[5:35, 5:35] = 255
    extraction = extract_ink(image, gt)
    assert extraction.status == "no_ink"
    assert extraction.unseparated == 0
    assert ink_report(gt, extraction)["recall"] is None


def test_colored_text_is_measured():
    image = np.full((40, 40, 3), 255, dtype=np.uint8)
    image[12:28, 12:28] = (210, 30, 40)
    gt = np.zeros((40, 40), dtype=np.uint8)
    gt[4:36, 4:36] = 255
    extraction = extract_ink(image, gt)
    assert extraction.status == "measured"
    assert extraction.ink_pixels > 0
    assert ink_report(gt, extraction)["recall"] == 1.0


def test_damage_counts_only_outside_the_allowed_zone():
    original = np.full((30, 30, 3), 10, dtype=np.uint8)
    cleaned = original.copy()
    cleaned[2:6, 2:6] = 200
    cleaned[20, 20] = 200
    allowed = np.zeros((30, 30), dtype=np.uint8)
    allowed[0:10, 0:10] = 255
    report = damage(original, cleaned, allowed, threshold=12)
    assert report["damaged_pixels"] == 1
    assert report["damage"] == 1 / int(np.sum(allowed == 0))
