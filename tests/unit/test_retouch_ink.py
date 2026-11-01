"""Светлые буквы на рисунке не должны теряться или захватывать рамки."""

import cv2
import numpy as np
from PIL import Image

from src.components.retouch_ink import boundary_ink, confirmed_light_ink, preserves_picture, smooth_line_mask
from src.components.adaptive_text import source_ink
from src.components.text_segmenter import segment_region
from src.models import TextRegion


def caption(background, outline=False):
    rgb = np.full((135, 320, 3), background, np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    for y, word in [(48, 'I WILL'), (105, 'LIKE ME')]:
        if outline:
            cv2.putText(rgb, word, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 8)
            cv2.putText(expected, word, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 8)
        cv2.putText(rgb, word, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        cv2.putText(expected, word, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 3)
    return rgb, expected


def test_light_text_keeps_every_stroke_on_dark_panel():
    rgb, expected = caption((35, 40, 45))
    cv2.line(rgb, (5, 8), (310, 8), (80, 80, 80), 2)
    found, outlined = confirmed_light_ink(rgb)
    assert found is not None and not outlined
    assert np.mean(found[expected > 0] > 0) >= .99
    assert not np.any(found[:12])


def test_inverse_outline_includes_solid_i_and_l_and_black_stroke():
    rgb, expected = caption((180, 130, 160), outline=True)
    found, outlined = confirmed_light_ink(rgb)
    assert outlined
    assert np.mean(found[expected > 0] > 0) >= .99
    assert not np.any(found[:, 270:])


def test_white_background_and_frame_are_not_light_letters():
    rgb = np.full((120, 220, 3), 255, np.uint8)
    cv2.rectangle(rgb, (4, 4), (215, 115), (0, 0, 0), 3)
    cv2.putText(rgb, 'WORDS', (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    found, _ = confirmed_light_ink(rgb)
    assert found is None


def test_yellow_text_is_not_partially_removed_as_white_core():
    rgb = np.full((110, 280, 3), (55, 30, 75), np.uint8)
    cv2.putText(rgb, 'CLACK', (25, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 8)
    cv2.putText(rgb, 'CLACK', (25, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 220, 55), 3)
    found, _ = confirmed_light_ink(rgb)
    assert found is None


def test_dark_bubble_mask_and_source_ink_preserve_bright_letters():
    rgb, expected = caption((35, 40, 45))
    region = TextRegion(1, (12, 12, 240, 105), text='I WILL LIKE ME', bubble_bbox=(3, 3, 310, 125))
    result = segment_region(rgb, region)
    assert np.mean(result[expected > 0] > 0) >= .99
    _, ink, (a, b, c, d) = source_ink(Image.fromarray(rgb), region)
    assert np.mean(ink[expected[b:d, a:c] > 0] > 0) >= .99


def test_transparent_panel_is_distinguished_from_opaque_paper():
    rgb, _ = caption((255, 255, 255))
    assert not preserves_picture(rgb)
    gradient = np.repeat(np.linspace(190, 255, rgb.shape[1], dtype=np.uint8)[None, :, None], rgb.shape[0], axis=0)
    gradient = np.repeat(gradient, 3, axis=2)
    assert preserves_picture(gradient)


def test_compressed_white_paper_is_not_treated_as_transparent():
    rgb, _ = caption((255, 255, 255))
    rgb[::3, ::2] = 225
    assert not preserves_picture(rgb)


def test_line_closure_is_limited_to_smooth_background():
    rgb, _ = caption((180, 130, 160), outline=True)
    ink, _ = confirmed_light_ink(rgb)
    closed = smooth_line_mask(rgb, ink)
    assert np.count_nonzero(closed) > np.count_nonzero(ink)
    assert not np.any(closed[:, 270:])
    detailed = rgb.copy()
    detailed[:, 270:] = np.random.default_rng(1).integers(0, 255, detailed[:, 270:].shape, dtype=np.uint8)
    assert np.array_equal(smooth_line_mask(detailed, ink), ink)


def test_boundary_extension_only_adds_crossing_components():
    rgb, _ = caption((180, 130, 160), outline=True)
    cv2.rectangle(rgb, (194, 55), (207, 70), (0, 0, 0), -1)
    cv2.rectangle(rgb, (198, 59), (203, 66), (255, 255, 255), -1)
    result = boundary_ink(Image.fromarray(rgb), (10, 10, 190, 115), (5, 5, 205, 130))
    assert result is not None
    mask, (a, b, c, d) = result
    assert mask[62-b, 206-a] > 0
    assert mask[45-b, 50-a] == 0
