"""Диагностическая близость к контролю не должна маскировать отсутствие изменений."""

import numpy as np
from PIL import Image

from scripts.eval_retouch import reference_similarity


def test_similarity_uses_only_annotated_zone():
    original = Image.new('RGB', (20, 20), 'black')
    reference = Image.new('RGB', (20, 20), 'white')
    zone = np.zeros((20, 20), np.uint8)
    zone[5:15, 5:15] = 255
    result = np.zeros((20, 20, 3), np.uint8)
    result[5:15, 5:15] = 255
    assert reference_similarity(original, Image.fromarray(result), reference, zone) == 1
    assert reference_similarity(original, original, reference, zone) == 0


def test_undefined_reference_is_not_reported_as_perfect():
    image = Image.new('RGB', (10, 10), 'white')
    zone = np.full((10, 10), 255, np.uint8)
    assert reference_similarity(image, image, image, zone) is None
    assert reference_similarity(image, image, image, np.zeros_like(zone)) is None
