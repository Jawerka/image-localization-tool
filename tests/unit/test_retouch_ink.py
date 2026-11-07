"""Светлые буквы на рисунке не должны теряться или захватывать рамки."""

import cv2
import numpy as np
from PIL import Image

from src.components.retouch_ink import boundary_ink, confirmed_light_ink, preserves_picture, smooth_light_mask, smooth_line_mask
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


def test_white_letters_on_midtone_colored_panels_are_not_outlines():
    for background in [(170, 190, 230), (112, 105, 164), (180, 130, 160)]:
        rgb, expected = caption(background)
        found, outlined = confirmed_light_ink(rgb)
        assert found is not None and not outlined
        assert np.mean(found[expected > 0] > 0) >= .99
        assert not np.any(found[:, 270:])


def test_bright_fields_and_border_highlights_on_colored_panel_are_rejected():
    rgb = np.full((135, 320, 3), (170, 190, 230), np.uint8)
    cv2.rectangle(rgb, (0, 0), (319, 134), (255, 255, 255), 4)
    cv2.rectangle(rgb, (30, 20), (130, 110), (255, 255, 255), -1)
    cv2.rectangle(rgb, (190, 20), (290, 110), (255, 255, 255), -1)
    found, _ = confirmed_light_ink(rgb)
    assert found is None


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


def test_coloured_outline_is_removed_with_light_cores():
    """Цветной ореол тоже часть надписи, а не восстанавливаемого фона."""
    for outline in [(55, 135, 135), (175, 145, 55)]:
        rgb = np.full((160, 400, 3), (100, 80, 95), np.uint8)
        expected = np.zeros(rgb.shape[:2], np.uint8)
        for y, word in [(65, 'YOUR'), (130, 'PRINCESS')]:
            cv2.putText(rgb, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, outline, 12)
            cv2.putText(expected, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 12)
            cv2.putText(rgb, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (235, 235, 235), 3)
        found, outlined = confirmed_light_ink(rgb)
        assert found is not None and outlined
        assert np.mean(found[expected > 0] > 0) >= .98
        assert not np.any(found[:, 320:])


def test_coloured_panel_is_not_an_outline_of_white_letters():
    """Однотонное облачко не расширяется до всей площади как ореол."""
    rgb, expected = caption((55, 135, 135))
    found, outlined = confirmed_light_ink(rgb)
    assert found is not None and not outlined
    assert not np.any(found[expected == 0])


def test_light_holes_in_coloured_letters_do_not_replace_dark_ink():
    """Светлые просветы цветных букв не превращают реплику в белую надпись."""
    rgb = np.full((135, 320, 3), (195, 220, 235), np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, 'BOOKS LOOK', (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (175, 105, 140), 4)
    cv2.putText(expected, 'BOOKS LOOK', (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 4)
    contours, _ = cv2.findContours(expected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = cv2.drawContours(np.zeros_like(expected), contours, -1, 255, -1)
    rgb[(filled > 0) & (expected == 0)] = 255
    region = TextRegion(1, (10, 30, 285, 60), text='BOOKS LOOK', block_type='dialogue',
                        bubble_bbox=(3, 3, 310, 125))
    captured = {}
    segment_region(rgb, region, capture_ink=captured)
    assert np.mean(captured[1][expected > 0] > 0) >= .95
    _, ink, (a, b, c, d) = source_ink(Image.fromarray(rgb), region)
    assert np.mean(ink[expected[b:d, a:c] > 0] > 0) >= .95


def test_dark_bubble_mask_and_source_ink_preserve_bright_letters():
    rgb, expected = caption((35, 40, 45))
    region = TextRegion(1, (12, 12, 240, 105), text='I WILL LIKE ME', bubble_bbox=(3, 3, 310, 125))
    result = segment_region(rgb, region)
    assert np.mean(result[expected > 0] > 0) >= .99
    _, ink, (a, b, c, d) = source_ink(Image.fromarray(rgb), region)
    assert np.mean(ink[expected[b:d, a:c] > 0] > 0) >= .99


def test_midtone_bubble_uses_white_glyphs_for_capture_and_cleanup_margin():
    rgb, expected = caption((170, 190, 230))
    region = TextRegion(1, (12, 12, 240, 105), text='I WILL LIKE ME', bubble_bbox=(3, 3, 310, 125))
    captured = {}
    result = segment_region(rgb, region, capture_ink=captured)
    assert np.mean(captured[1][expected > 0] > 0) >= .99
    margin = cv2.dilate(expected, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    assert np.mean(result[margin > 0] > 0) >= .99
    assert region._retouch_preserve_background
    assert not np.any(result[:, 270:])


def test_light_envelope_only_closes_gaps_on_smooth_background():
    rgb, expected = caption((170, 190, 230))
    closed = smooth_light_mask(rgb, expected)
    assert np.all(closed[expected > 0] > 0)
    assert closed[65, 60] > 0
    assert not np.any(closed[:, 270:])
    detailed = np.random.default_rng(7).integers(0, 255, rgb.shape, dtype=np.uint8)
    assert np.array_equal(smooth_light_mask(detailed, expected), expected)


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


def test_coloured_outline_on_texture_follows_letter_cores():
    """Цветная оболочка закрывается вокруг ядер даже на шумном фоне."""
    rng = np.random.default_rng(0)
    rgb = rng.integers(40, 140, (160, 400, 3), dtype=np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    outline = (55, 135, 135)
    for y, word in [(65, 'YOUR'), (130, 'PRINCESS')]:
        cv2.putText(rgb, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, outline, 12)
        cv2.putText(expected, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 12)
        cv2.putText(rgb, word, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (235, 235, 235), 3)
    found, outlined = confirmed_light_ink(rgb)
    assert found is not None and outlined
    assert np.mean(found[expected > 0] > 0) >= .90
    assert np.mean(found > 0) < .35


def test_short_coloured_word_keeps_outline():
    """Короткое слово из нескольких букв не теряется из-за одной компоненты оболочки."""
    rgb = np.full((80, 180, 3), (90, 70, 80), np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, 'FUFU', (12, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (55, 135, 135), 10)
    cv2.putText(expected, 'FUFU', (12, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 10)
    cv2.putText(rgb, 'FUFU', (12, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (235, 235, 235), 3)
    found, outlined = confirmed_light_ink(rgb)
    assert found is not None and outlined
    assert np.mean(found[expected > 0] > 0) >= .90


def test_outline_clipped_by_crop_edge_stays_in_region_mask():
    """Обводка, обрезанная ROI, добирается в маску ретуши, если ядро внутри."""
    rgb = np.full((80, 160, 3), (90, 70, 80), np.uint8)
    outline, fill = (55, 135, 135), (235, 235, 235)
    for x0 in (24, 58):
        cv2.rectangle(rgb, (x0, 22), (x0 + 24, 58), outline, -1)
        cv2.rectangle(rgb, (x0 + 5, 27), (x0 + 19, 53), fill, -1)
    crop = rgb[:, 26:]
    found, outlined = confirmed_light_ink(crop)
    assert found is not None and outlined
    assert np.any(found[:, :3])
    region = TextRegion(1, (26, 16, 70, 52), text='HI', block_type='dialogue',
                        bubble_bbox=(8, 8, 140, 64))
    result = segment_region(rgb, region)
    assert result[40, 24] > 0
    assert result[40, 36] > 0


def test_gradient_panel_without_letter_cores_is_not_an_outline():
    """Градиентная плашка без буквенных ядер не становится маской ретуши."""
    ramp = np.linspace((40, 80, 160), (200, 120, 80), 160, dtype=np.uint8)
    rgb = np.repeat(ramp[None, :, :], 80, axis=0)
    found, outlined = confirmed_light_ink(rgb)
    assert found is None
    assert not outlined
