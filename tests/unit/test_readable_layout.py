"""Регрессии потери реплики, неполного контура и автоматической обводки."""
import copy
import cv2
import numpy as np
from PIL import Image, ImageDraw
from src.models import TextRegion, TextStyle
from src.components.adaptive_text import geometry_area
from src.components.typesetter import Typesetter, _complete_fallback, _font_file
from src.components.bubble_layout import light_layout_area, balloon_body


def test_partial_first_line_contour_is_rejected():
    region = TextRegion(1, (30, 30, 140, 80), bubble_bbox=(10, 10, 180, 120),
                        auto_layout={'version': 1, 'kind': 'bubble',
                                     'contour': [[30, 30], [170, 30], [170, 48], [30, 48]]})
    assert geometry_area((140, 200), region) is None
    image = np.full((140, 200, 3), 70, np.uint8)
    cv2.ellipse(image, (100, 70), (86, 56), 0, 0, 360, (235, 235, 235), -1)
    partial = np.zeros((140, 200), np.uint8)
    partial[30:49, 30:170] = 255
    area = light_layout_area(image, region, partial)
    assert np.mean(area[30:110, 30:170] > 0) > .9


def test_emergency_layout_keeps_every_word():
    region = TextRegion(1, (20, 20, 130, 45), translation='Мы можем лишь надеяться на это!')
    draw = ImageDraw.Draw(Image.new('RGB', (180, 100)))
    placed, font = _complete_fallback(region.translation, region, _font_file(region), draw,
                                     None, 10, 0, 0, lambda size: 1)
    assert ' '.join(line for line, _, _ in placed) == region.translation
    assert font.size > 0


def test_automatic_outline_is_white_and_manual_modes_survive():
    image = Image.new('RGB', (250, 150), (100, 130, 170))
    region = TextRegion(1, (35, 40, 180, 65), bubble_bbox=(10, 10, 230, 130),
                        text='Hello', translation='Привет',
                        auto_layout={'version': 1, 'kind': 'bubble'},
                        style=TextStyle(font_size_override=28))
    setter = Typesetter()
    result, overflow = setter.render(image, [region])
    assert not overflow
    pixels = np.array(result)
    assert np.count_nonzero(np.all(pixels > 245, axis=2)) > 20
    for mode, width in [('none', 0), ('custom', 3)]:
        manual = copy.deepcopy(region)
        manual.style.stroke_mode = mode
        manual.style.stroke_width = 3
        manual.style.stroke_rgb = (200, 10, 20)
        area = np.full((150, 250), 255, np.uint8)
        color, actual = setter._stroke_paint(np.array(image), area, manual, 28)
        assert actual == width
        if mode == 'custom': assert color == (200, 10, 20)


def test_thin_tail_does_not_set_balloon_body_center():
    mask = np.zeros((140, 240), np.uint8)
    cv2.ellipse(mask, (150, 65), (65, 48), 0, 0, 360, 255, -1)
    cv2.line(mask, (90, 70), (12, 128), 255, 5)
    region = TextRegion(1, (110, 40, 80, 50), bubble_bbox=(10, 10, 210, 120))
    body = balloon_body(mask, region)
    assert not body[127, 13]
    assert np.all(body[40:90, 110:190])
