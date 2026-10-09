"""Заливка ровного фона и маска кропа LaMa без вызова модели."""

import numpy as np
from PIL import Image

from src.components.lama_inpainter import (
    LamaInpainter,
    _EDGE_FEATHER_PX,
    _LAMA_MASK_DILATE,
    _RING_INK_DISTANCE,
    _RING_INLIER_RATIO,
    _TILE,
    _ceil_mod,
    _edge_alpha,
    _window_bounds,
)


def test_ring_and_mask_dilation_are_tight():
    assert _LAMA_MASK_DILATE <= 3
    assert _RING_INK_DISTANCE == 40.0
    assert _RING_INLIER_RATIO == 0.85
    assert _EDGE_FEATHER_PX >= 1


def test_edge_alpha_zero_feather_is_hard_mask():
    hole = np.zeros((20, 20), dtype=np.uint8)
    hole[5:15, 5:15] = 255
    alpha = _edge_alpha(hole, 0)
    assert alpha.dtype == np.float32
    assert float(alpha[10, 10]) == 1.0
    assert float(alpha[0, 0]) == 0.0
    assert float(alpha[5, 5]) == 1.0


def test_edge_alpha_ramps_from_border_to_core():
    hole = np.zeros((40, 40), dtype=np.uint8)
    hole[8:32, 8:32] = 255
    alpha = _edge_alpha(hole, 4)
    assert float(alpha[8, 20]) < float(alpha[12, 20]) <= float(alpha[20, 20])
    assert float(alpha[20, 20]) == 1.0


def test_paste_component_soft_blends_edge_and_keeps_core():
    image = np.zeros((30, 30, 3), dtype=np.uint8)
    image[:] = (0, 0, 0)
    component = np.zeros((30, 30), dtype=np.uint8)
    component[5:25, 5:25] = 255
    predicted = np.full((30, 30, 3), 255, dtype=np.uint8)
    out = LamaInpainter._paste_component(image, component, predicted, 0, 0, feather_px=4)
    # Ядро — почти полностью predicted.
    assert int(out[15, 15, 0]) >= 250
    # У края дырки — смесь с чёрным оригиналом.
    edge = int(out[5, 15, 0])
    assert 0 < edge < 255


def test_paste_component_feather_zero_is_hard_replace():
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    component = np.zeros((20, 20), dtype=np.uint8)
    component[4:16, 4:16] = 255
    predicted = np.full((20, 20, 3), 200, dtype=np.uint8)
    out = LamaInpainter._paste_component(image, component, predicted, 0, 0, feather_px=0)
    assert int(out[10, 10, 0]) == 200
    assert int(out[4, 10, 0]) == 200
    assert int(out[0, 0, 0]) == 0


def test_lama_mask_dilation_does_not_reach_far_neighbor():
    """Узкая дилатация маски LaMa не должна захватывать глиф в 5 px от края дырки."""
    image = np.full((100, 160, 3), 180, dtype=np.uint8)
    image[40:60, 20:70] = 0
    image[40:60, 75:90] = 0  # сосед через зазор ~5 px
    mask = np.zeros((100, 160), dtype=np.uint8)
    mask[40:60, 20:70] = 255
    seen: list[np.ndarray] = []

    def fake_lama(rgb, component, lama_mask):
        seen.append(lama_mask.copy())
        out = rgb.copy()
        out[component > 0] = 200
        return out

    inpainter = LamaInpainter(device="cpu")
    inpainter._lama_crop = fake_lama
    # allow_flat_fill False — сразу в LaMa на шумном фоне
    inpainter.inpaint(Image.fromarray(image), mask, allow_flat_fill=False)
    assert seen
    dilated = seen[0]
    # Соседняя буква (колонка 80) не должна попасть в расширенную маску окна.
    assert int(dilated[50, 80]) == 0


def test_neighbor_ink_in_ring_keeps_flat_fill_and_neighbor():
    """Соседняя буква в кольце не должна срывать плоскую заливку и звать LaMa."""
    image = np.full((100, 160, 3), 255, dtype=np.uint8)
    image[40:60, 20:70] = 0
    image[40:60, 78:95] = 0
    mask = np.zeros((100, 160), dtype=np.uint8)
    mask[40:60, 20:70] = 255

    inpainter = LamaInpainter(device="cpu")
    calls = {"n": 0}

    def fail(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("LaMa не должна вызываться")

    inpainter._lama_crop = fail
    result = np.array(inpainter.inpaint(Image.fromarray(image), mask))
    assert calls["n"] == 0
    assert int(result[50, 40].min()) > 250
    assert int(result[50, 85].max()) == 0


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
    assert inpainter.last_warnings == []
    for item in seen:
        crop_mask = item[0, 0]
        assert crop_mask[40:70, 40:90].mean() > 0.9
        assert crop_mask[40:70, 110:160].mean() > 0.9


def test_lama_failure_records_opencv_fallback_warning():
    """Шумный фон не даёт плоскую заливку; падение LaMa → OpenCV + warning."""
    rng = np.random.default_rng(4)
    image = rng.integers(0, 256, size=(120, 160, 3), dtype=np.uint8)
    mask = np.zeros((120, 160), dtype=np.uint8)
    mask[40:80, 40:120] = 255

    inpainter = LamaInpainter(device="cpu")

    def fail(*args, **kwargs):
        raise RuntimeError("lama boom")

    inpainter._lama_crop = fail
    result = inpainter.inpaint(Image.fromarray(image), mask)
    assert result.size == (160, 120)
    assert any("OpenCV" in note and "LaMa" in note for note in inpainter.last_warnings)


def _stub_sizes():
    sizes: list[tuple[int, int]] = []

    class FakeLama:
        def __call__(self, image_t, mask_t):
            sizes.append((int(image_t.shape[-2]), int(image_t.shape[-1])))
            return image_t * 0 + 1

    return sizes, FakeLama()


def test_large_window_is_tiled_without_downscale():
    rng = np.random.default_rng(2)
    image = rng.integers(0, 256, size=(100, 1800, 3), dtype=np.uint8)
    mask = np.zeros((100, 1800), dtype=np.uint8)
    mask[40:60, 100:1700] = 255
    outside = image[10, 10].copy()

    sizes, model = _stub_sizes()
    inpainter = LamaInpainter(device="cpu")
    inpainter._model = model
    result = np.array(inpainter.inpaint(Image.fromarray(image), mask))

    assert len(sizes) > 1
    assert all(side <= _TILE for height, width in sizes for side in (height, width))
    assert int(result[50, 400].min()) == 255
    assert np.array_equal(result[10, 10], outside)


def test_short_stroke_is_one_full_size_pass():
    rng = np.random.default_rng(3)
    image = rng.integers(0, 256, size=(400, 400, 3), dtype=np.uint8)
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[180:200, 180:230] = 255
    bounds = _window_bounds(mask, image.shape[:2], pad=128)
    assert bounds is not None
    y0, x0, y1, x1 = bounds

    sizes, model = _stub_sizes()
    inpainter = LamaInpainter(device="cpu")
    inpainter._model = model
    inpainter.inpaint(Image.fromarray(image), mask)

    assert sizes == [(_ceil_mod(y1 - y0), _ceil_mod(x1 - x0))]
