"""Регрессии раскладки по ширине каждой полосы облачка."""

import cv2
import numpy as np
from PIL import Image, ImageDraw

from src.components.bubble_layout import layout_in_shape
from src.components.typesetter import (
    _font_file,
    _load_font,
    _row_spans,
)
from src.models import TextRegion


def test_neighbour_bubbles_get_disjoint_layout_without_changing_mask():
    from src.components.bubble_layout import separate_neighbour_bubbles

    mask = np.full((120, 220), 255, np.uint8)
    left = TextRegion(1, (20, 20, 60, 70), bubble_bbox=(0, 0, 120, 120), translation="Левая")
    right = TextRegion(2, (100, 20, 60, 70), bubble_bbox=(90, 0, 120, 120), translation="Правая")
    a = separate_neighbour_bubbles(mask, left, [left, right])
    b = separate_neighbour_bubbles(mask, right, [left, right])
    assert not np.any((a > 0) & (b > 0))
    assert np.all(a[20:90, 20:80]) and np.all(b[20:90, 100:160])
    assert np.all(mask == 255)
    right.skip = True
    assert np.array_equal(separate_neighbour_bubbles(mask, left, [left, right]), mask)


def test_stacked_neighbour_bubbles_are_separated_vertically():
    from src.components.bubble_layout import separate_neighbour_bubbles

    mask = np.full((220, 120), 255, np.uint8)
    top = TextRegion(1, (20, 20, 70, 60), bubble_bbox=(0, 0, 120, 120), translation="Верх")
    bottom = TextRegion(2, (20, 100, 70, 60), bubble_bbox=(0, 90, 120, 120), translation="Низ")
    a = separate_neighbour_bubbles(mask, top, [top, bottom])
    b = separate_neighbour_bubbles(mask, bottom, [top, bottom])
    assert not np.any((a > 0) & (b > 0))
    assert np.all(a[20:80, 20:90]) and np.all(b[100:160, 20:90])


def test_shape_layout_preserves_words_and_band_bounds():
    mask = np.zeros((220, 400), np.uint8)
    cv2.ellipse(mask, (200, 110), (185, 95), 0, 0, 360, 255, -1)
    region = TextRegion(1, (50, 50, 300, 120), bubble_bbox=(15, 15, 370, 190))
    font = _load_font(_font_file(region), 27)
    draw = ImageDraw.Draw(Image.new("RGB", (400, 220)))
    text = "ЭТО ПИСЬМО ОТ ПРИНЦЕССЫ И ЕЩЁ НЕСКОЛЬКО СЛОВ"
    placed, fits = layout_in_shape(text, font, draw, _row_spans(mask), None, "center")
    assert fits
    assert " ".join(line for line, _, _ in placed) == text
    for line, x, y in placed:
        left, top, right, bottom = draw.textbbox((x, y), line, font=font)
        assert np.all(mask[top:bottom, left:right] > 0)


def test_gap_in_shape_is_not_usable_text_space():
    spans = [None] * 100
    placed, fits = layout_in_shape(
        "ТЕКСТ",
        _load_font(None, 15),
        ImageDraw.Draw(Image.new("RGB", (100, 100))),
        spans,
        None,
        "center",
    )
    assert not fits and not placed


def test_fit_stroke_width_matches_render_width():
    from src.components.typesetter import Typesetter
    from src.models import TextStyle

    for complex_bg in (False, True):
        rgb = np.full((50, 50, 3), 255, np.uint8)
        if complex_bg:
            rgb[:25] = 0
        area = np.full((50, 50), 255, np.uint8)
        for ratio in (0, 0.08, 0.2):
            setter = Typesetter(stroke_ratio=ratio)
            for mode in ("auto", "none", "custom"):
                r = TextRegion(
                    1, (0, 0, 50, 50), style=TextStyle(stroke_mode=mode, stroke_width=3)
                )
                for size in (10, 23, 52, 128):
                    assert (
                        setter._fit_stroke_width(r, size, complex_bg)
                        == setter._stroke_paint(rgb, area, r, size)[1]
                    )


def test_separated_tails_do_not_form_a_wide_line():
    from src.components.bubble_layout import shape_row_spans

    mask = np.zeros((20, 100), np.uint8)
    mask[:10, 10:90] = 255
    mask[10:, 10:13] = 255
    mask[10:, 87:90] = 255
    spans = shape_row_spans(mask)
    assert spans[5] == (10, 89)
    assert spans[15][1] - spans[15][0] == 2
