"""Заливка ровного фона и маска кропа LaMa без вызова модели."""

import numpy as np
from PIL import Image

from src.components.lama_inpainter import LamaInpainter


def test_close_lines_on_white_are_filled_without_lama():
    image = np.full((100, 180, 3), 255, dtype=np.uint8)
    image[30:48, 30:140] = 0
    image[50:68, 30:140] = 0
    image[28:30, 30:140] = 240
    mask = np.zeros((100, 180), dtype=np.uint8)
    mask[30:48, 30:140] = 255
    mask[50:68, 30:140] = 255

    inpainter = LamaInpainter(device="cpu")
    calls = {"n": 0}

    def fail(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("LaMa не должна вызываться")

    inpainter._lama_crop = fail
    result = np.array(inpainter.inpaint(Image.fromarray(image), mask))
    assert calls["n"] == 0
    assert int(result[40, 80].max()) > 250
    assert int(result[58, 80].max()) > 250
    assert int(result[29, 80].max()) > 250


def test_text_near_outline_does_not_erase_the_outline():
    image = np.full((120, 160, 3), 255, dtype=np.uint8)
    image[10:110, 10:13] = 0
    image[10:110, 147:150] = 0
    image[10:13, 10:150] = 0
    image[107:110, 10:150] = 0
    image[40:70, 18:90] = 0
    image[40:70, 15:18] = 236
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    mask[40:70, 18:90] = 255

    inpainter = LamaInpainter(device="cpu")

    def fail(*args, **kwargs):
        raise RuntimeError("LaMa не должна вызываться")

    inpainter._lama_crop = fail
    result = np.array(inpainter.inpaint(Image.fromarray(image), mask))
    assert int(result[50, 11].max()) == 0
    assert int(result[50, 16].min()) > 240
    assert int(result[55, 40].min()) > 250


def test_halo_around_flat_fill_is_cleared():
    image = np.full((80, 140, 3), 255, dtype=np.uint8)
    image[30:50, 30:100] = 0
    image[29, 40:90] = 236
    image[50, 40:90] = 240
    image[29, 35] = 0
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    mask[30:50, 30:100] = 255

    inpainter = LamaInpainter(device="cpu")
    result = np.array(inpainter.inpaint(Image.fromarray(image), mask))
    assert int(result[29, 60].min()) > 250
    assert int(result[50, 60].min()) > 250
    assert int(result[40, 60].min()) > 250
    assert int(result[29, 35].max()) == 0


def test_lama_crop_mask_includes_the_whole_window():
    rng = np.random.default_rng(1)
    image = rng.integers(0, 256, size=(180, 320, 3), dtype=np.uint8)
    mask = np.zeros((180, 320), dtype=np.uint8)
    mask[40:70, 40:90] = 255
    mask[40:70, 110:160] = 255
    seen: list[np.ndarray] = []

    class FakeLama:
        def __call__(self, image_t, mask_t):
            seen.append(mask_t.detach().cpu().numpy() > 0.5)
            return image_t

    inpainter = LamaInpainter(device="cpu")
    inpainter._model = FakeLama()
    inpainter.inpaint(Image.fromarray(image), mask)
    assert len(seen) == 2
    for item in seen:
        crop_mask = item[0, 0]
        assert crop_mask[40:70, 40:90].mean() > 0.9
        assert crop_mask[40:70, 110:160].mean() > 0.9
