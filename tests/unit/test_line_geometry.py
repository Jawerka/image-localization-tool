"""Отдельные наклоны строк и перспектива без уменьшения текста."""
import cv2
import numpy as np
import pytest

from src.components.line_geometry import line_frame, render_line_frame
from src.components.typesetter import COMIC_FONT


@pytest.mark.parametrize('angle', [-23, -9, 0, 17])
def test_each_instance_keeps_its_own_angle(angle):
    mask = np.zeros((260, 500), np.uint8)
    box = cv2.boxPoints(((250, 130), (360, 60), -angle))
    cv2.fillPoly(mask, [np.round(box).astype(np.int32)], 255)
    frame = line_frame(mask)
    assert frame is not None
    assert abs(frame['angle']-angle) < 1
    assert frame['kind'] == 'rbox'


def test_perspective_uses_quad_and_full_fixed_font_text():
    mask = np.zeros((200, 420), np.uint8)
    cv2.fillPoly(mask, [np.int32([[30, 30], [380, 70], [300, 145], [55, 100]])], 255)
    frame = line_frame(mask)
    assert frame['kind'] == 'quad'
    layer, fit = render_line_frame('ПРИМЕР ТЕКСТА', COMIC_FONT, 24, frame, (420, 200))
    assert layer is not None and fit['fits']
    assert fit['font_size'] == 24
    assert ' '.join(row['text'] for row in fit['lines']) == 'ПРИМЕР ТЕКСТА'
    alpha = np.asarray(layer.getchannel('A')) > 127
    assert not np.any(alpha & (mask == 0))


def test_geometry_does_not_shrink_long_unbreakable_word():
    mask = np.zeros((80, 180), np.uint8)
    mask[20:60, 20:160] = 255
    frame = line_frame(mask)
    layer, fit = render_line_frame('Электроэнцефалографический', COMIC_FONT, 32, frame, (180, 80))
    assert layer is None and not fit['fits'] and fit['font_size'] == 32
