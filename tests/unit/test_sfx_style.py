"""Оценка стиля по маске чернил: угол, заливка, обводка, базовая линия."""

import numpy as np

from src.components.sfx_style import estimate_style

_STYLE_KEYS = {
    "fill_rgb",
    "stroke_rgb",
    "stroke_width",
    "stroke_mode",
    "rotation",
    "warp",
}


def _horizontal_bar() -> tuple[np.ndarray, np.ndarray]:
    """Белая горизонтальная полоса на чёрном."""
    image = np.zeros((80, 220, 3), dtype=np.uint8)
    mask = np.zeros((80, 220), dtype=np.uint8)
    image[34:46, 20:200] = 255
    mask[34:46, 20:200] = 255
    return image, mask


def test_horizontal_bar_near_zero_and_light_fill():
    """Горизонтальная полоса: поворот около 0°, заливка светлая."""
    image, mask = _horizontal_bar()
    style = estimate_style(image, mask)
    assert set(style) == _STYLE_KEYS
    assert abs(float(style["rotation"])) < 15.0
    assert style["stroke_mode"] == "auto"
    fill = np.asarray(style["fill_rgb"], dtype=np.float32)
    assert fill.shape == (3,)
    assert float(fill.mean()) > 200.0
    assert np.all(fill > 200.0)


def test_diagonal_bar_rotated():
    """Полоса вверх-вправо заметно повёрнута относительно горизонтали."""
    height, width = 180, 180
    image = np.zeros((height, width, 3), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    for offset in range(120):
        x = 30 + offset
        y = 140 - offset
        image[y - 3:y + 4, x - 2:x + 3] = 255
        mask[y - 3:y + 4, x - 2:x + 3] = 255
    style = estimate_style(image, mask)
    assert abs(float(style["rotation"])) > 10.0


def test_thick_ring_stroke_differs_from_fill():
    """Красное ядро и толстое синее кольцо внутри одной маски."""
    height, width = 140, 140
    image = np.zeros((height, width, 3), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    yy, xx = np.ogrid[:height, :width]
    radius = np.sqrt((yy - 70) ** 2 + (xx - 70) ** 2)
    interior = radius <= 26
    ring = (radius > 26) & (radius <= 52)
    image[interior] = (220, 20, 20)
    image[ring] = (20, 30, 230)
    mask[interior | ring] = 255
    style = estimate_style(image, mask)
    fill = np.asarray(style["fill_rgb"], dtype=np.float32)
    stroke = np.asarray(style["stroke_rgb"], dtype=np.float32)
    assert np.any(np.abs(fill - stroke) > 15.0)
    assert float(style["stroke_width"]) > 1.0


def test_straight_bar_warp_is_flat():
    """Прямая полоса: у warp есть четыре ключа, quad и mesh пустые, изгиба нет."""
    image, mask = _horizontal_bar()
    warp = estimate_style(image, mask)["warp"]
    assert set(warp) == {"kind", "bend", "quad", "mesh"}
    assert warp["quad"] is None
    assert warp["mesh"] is None
    assert warp["kind"] == "none" or abs(float(warp["bend"])) < 0.05


def test_empty_mask_returns_defaults():
    """Пустая маска не падает и отдаёт нейтральный стиль."""
    image = np.zeros((24, 24, 3), dtype=np.uint8)
    mask = np.zeros((24, 24), dtype=np.uint8)
    style = estimate_style(image, mask)
    assert set(style) == _STYLE_KEYS
    assert style["fill_rgb"] == [0, 0, 0]
    assert style["stroke_rgb"] == [0, 0, 0]
    assert style["stroke_width"] == 0.0
    assert style["stroke_mode"] == "auto"
    assert style["rotation"] == 0.0
    assert style["warp"] == {"kind": "none", "bend": 0.0, "quad": None, "mesh": None}


def test_merge_sfx_keeps_straight_layout_and_copies_fill():
    """Вертикальные чернила не поворачивают блок. Заливка при auto всё ещё берётся с маски."""
    from src.models import TextRegion
    from src.page_pipeline import _merge_sfx_style

    image = np.zeros((180, 80, 3), dtype=np.uint8)
    mask = np.zeros((180, 80), dtype=np.uint8)
    image[20:160, 30:50] = (240, 10, 10)
    mask[20:160, 30:50] = 255
    region = TextRegion(id=1, bbox=(0, 0, 80, 180), block_type="sfx")
    _merge_sfx_style(region, image, mask)
    assert region.style.rotation == 0.0
    assert region.style.warp["kind"] == "none"
    assert region.style.warp["bend"] == 0.0
    assert region.style.warp["quad"] is None
    assert region.style.warp["mesh"] is None
    fill = np.asarray(region.style.fill_rgb, dtype=np.float32)
    assert fill[0] > 200.0
    assert fill[1] < 40.0
