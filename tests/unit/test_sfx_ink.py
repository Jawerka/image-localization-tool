"""Обводка звука и линии рисунка на синтетическом кропе."""

import cv2
import numpy as np

from src.components.sfx_ink import drop_line_components, outlined_glyphs
from src.components.text_segmenter import segment_region
from src.models import TextRegion


def test_outlined_glyphs_cover_letters_not_the_crop():
    """Чёрные буквы с белой обводкой на шумном тёмном фоне — не прямоугольник."""
    rgb = np.full((90, 220, 3), (30, 40, 35), np.uint8)
    noise = np.random.default_rng(0).integers(0, 40, rgb.shape, dtype=np.uint8)
    rgb = np.clip(rgb.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "BANG", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 8)
    cv2.putText(expected, "BANG", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 8)
    cv2.putText(rgb, "BANG", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (10, 10, 10), 2)
    cv2.putText(expected, "BANG", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 2)
    mask = outlined_glyphs(rgb)
    assert mask is not None
    assert np.count_nonzero(mask) < rgb.shape[0] * rgb.shape[1] * 0.45
    assert np.mean(mask[expected > 0] > 0) >= 0.8


def test_drop_line_components_keeps_letters():
    """Тонкая длинная линия рядом с тремя буквами не остаётся в маске."""
    binary = np.zeros((60, 160), np.uint8)
    binary[22:42, 20:36] = 255
    binary[22:42, 50:66] = 255
    binary[22:42, 80:96] = 255
    binary[8:11, 4:150] = 255
    result = drop_line_components(binary)
    assert result[30, 28] == 255
    assert result[9, 80] == 0
    assert np.count_nonzero(result) < np.count_nonzero(binary)


def test_polarity_prefers_even_strokes_over_larger_artwork():
    """Белые пятна разной толщины внутри чёрного контура не побеждают ровные буквы."""
    rgb = np.full((140, 280, 3), (120, 120, 120), np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "BANG", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 6)
    cv2.putText(expected, "BANG", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 6)
    cv2.putText(rgb, "BANG", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (8, 8, 8), 2)
    cv2.putText(expected, "BANG", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 2)
    for center, radius in (((200, 40), 5), ((230, 90), 11), ((180, 100), 22)):
        cv2.circle(rgb, center, radius + 3, (0, 0, 0), 3)
        cv2.circle(rgb, center, radius, (250, 250, 250), -1)
    mask = outlined_glyphs(rgb)
    assert mask is not None
    assert np.mean(mask[expected > 0] > 0) >= 0.55
    assert mask[100, 180] == 0


def test_thick_artwork_mass_is_cut_from_letters():
    """Толстый диск, прилипший к буквам, не входит в маску."""
    rgb = np.full((110, 260, 3), (90, 90, 90), np.uint8)
    cv2.putText(rgb, "KISS", (16, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 7)
    cv2.putText(rgb, "KISS", (16, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (5, 5, 5), 2)
    cv2.circle(rgb, (210, 58), 28, (255, 255, 255), 3)
    cv2.circle(rgb, (210, 58), 24, (5, 5, 5), -1)
    mask = outlined_glyphs(rgb)
    assert mask is not None
    assert mask[58, 210] == 0
    assert np.count_nonzero(mask[40:90, 16:150]) > 40


def test_panel_gutter_is_not_a_row_of_letters():
    """Белая полоса от края до края не становится маской звука."""
    rgb = np.full((90, 220, 3), (140, 140, 140), np.uint8)
    rgb[32:36, :] = (0, 0, 0)
    rgb[36:52, :] = (255, 255, 255)
    rgb[52:56, :] = (0, 0, 0)
    assert outlined_glyphs(rgb) is None
    cv2.putText(rgb, "HI", (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4)
    cv2.putText(rgb, "HI", (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1)
    mask = outlined_glyphs(rgb)
    if mask is not None:
        assert np.count_nonzero(mask[36:52, :]) == 0


def test_dialogue_bubble_is_not_treated_as_sfx_ink():
    """Облачко с репликой по-прежнему закрывается силуэтом, а не только буквами."""
    rgb = np.full((120, 180, 3), 255, np.uint8)
    cv2.ellipse(rgb, (90, 60), (70, 40), 0, 0, 360, (0, 0, 0), 2)
    cv2.putText(rgb, "HI", (70, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    region = TextRegion(1, (60, 40, 50, 30), text="HI", block_type="dialogue", bubble_bbox=(20, 20, 140, 80))
    mask = segment_region(rgb, region)
    assert mask[60, 90] == 255
    assert mask[2, 2] == 0
    assert np.count_nonzero(mask) > 2000
