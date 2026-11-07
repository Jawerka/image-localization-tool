"""Пиксельная маска на синтетическом кропе."""

import cv2
import numpy as np
from PIL import Image, ImageDraw

from src.components.text_segmenter import _colors, _outlined_text_mask, apply_strokes, segment_region
from src.models import MaskStroke, TextRegion


def test_unbound_light_dialogue_rescues_letters_without_erasing_border_art():
    """Тёмный рисунок у кольца ROI не отменяет буквы светлой реплики."""
    rgb = np.full((125, 220, 3), 255, np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    for text, point in [('WHAT', (20, 43)), ('NOW?', (20, 83))]:
        cv2.putText(rgb, text, point, cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
        cv2.putText(expected, text, point, cv2.FONT_HERSHEY_SIMPLEX, .8, 255, 2)
    cv2.line(rgb, (175, 0), (175, 124), (0, 0, 0), 4)
    region = TextRegion(1, (10, 10, 180, 90), text='WHAT NOW?', block_type='dialogue')
    captured = {}
    mask = segment_region(rgb, region, capture_ink=captured)
    assert np.mean(mask[expected > 0] > 0) >= .99
    assert np.mean(captured[1][expected > 0] > 0) >= .99
    assert np.count_nonzero(mask[:, 170:180]) == 0


def test_dense_outlined_caption_preserves_dark_cores_and_halo():
    """Плотная белая обводка не должна инвертироваться в фон и точки."""
    rgb = np.full((100, 240, 3), (20, 65, 60), dtype=np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    for y in (35, 70):
        cv2.putText(rgb, "WORDS", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 9)
        cv2.putText(expected, "WORDS", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 9)
        cv2.putText(rgb, "WORDS", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (25, 15, 20), 2)
    region = TextRegion(1, (12, 10, 115, 70), bubble_bbox=(8, 5, 125, 80))
    mask = segment_region(rgb, region)
    assert np.mean(mask[expected > 0] > 0) >= 0.99
    assert np.count_nonzero(mask[:, 140:]) == 0


def test_outlined_dialogue_masks_text_without_filling_bubble():
    """У текста с обводкой пустой интерьер облачка остаётся вне ретуши."""
    rgb = np.full((140, 240, 3), 40, np.uint8)
    cv2.rectangle(rgb, (15, 15), (225, 125), (210, 215, 215), -1)
    cv2.putText(rgb, "HELLO", (45, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 8)
    cv2.putText(rgb, "HELLO", (45, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (25, 15, 20), 2)
    region = TextRegion(1, (35, 48, 125, 42), bubble_bbox=(15, 15, 210, 110))
    mask = segment_region(rgb, region)
    letters = np.all(rgb == (25, 15, 20), axis=2)
    assert np.all(mask[letters] == 255)
    assert mask[30, 30] == 0
    assert mask[110, 200] == 0


def test_wide_light_bubble_is_not_a_letter_halo():
    """Светлый фон вокруг букв не должен включать режим узкой обводки."""
    rgb = np.full((160, 320, 3), (255, 120, 235), np.uint8)
    cv2.ellipse(rgb, (160, 80), (145, 65), 0, 0, 360, (255, 240, 255), -1)
    cv2.putText(rgb, "O-OH WOW", (50, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 20, 30), 3)
    assert _outlined_text_mask(rgb) is None


def test_partial_outline_keeps_unoutlined_words_and_source_ink():
    """Обводка только у части фразы не отменяет остальные тёмные буквы."""
    rgb = np.full((110, 310, 3), 205, np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "ONE", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 8)
    for text, pos in [("ONE", (20, 45)), ("TWO WORDS", (20, 90))]:
        cv2.putText(rgb, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 1, (15, 15, 15), 2)
        cv2.putText(expected, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
    assert _outlined_text_mask(rgb) is not None
    region = TextRegion(1, (10, 10, 270, 90), text="ONE TWO WORDS",
                        bubble_bbox=(0, 0, 310, 110))
    captured = {}
    mask = segment_region(rgb, region, capture_ink=captured)
    assert np.mean(mask[expected > 0] > 0) >= .99
    assert np.mean(captured[1][expected > 0] > 0) >= .99
    assert np.count_nonzero(mask[:, 290:]) == 0


def test_partial_outline_sfx_preserves_both_lines():
    """То же правило действует в локальном пути чернил SFX без бокса баллона."""
    rgb = np.full((110, 200, 3), 205, np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "DUMP", (15, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 8)
    for text, pos in [("BA-", (30, 40)), ("DUMP", (15, 90))]:
        cv2.putText(rgb, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 1, (15, 15, 15), 2)
        cv2.putText(expected, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
    region = TextRegion(1, (5, 5, 180, 100), text="BA-DUMP", block_type="sfx")
    mask = segment_region(rgb, region)
    assert np.mean(mask[expected > 0] > 0) >= .99


def test_segmenter_covers_dark_letters_and_reads_style():
    image = Image.new("RGB", (120, 60), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 16, 90, 40), fill="black")
    region = TextRegion(id=1, bbox=(10, 8, 100, 44), text="HELLO")
    mask = segment_region(np.array(image), region)
    assert mask[28, 50] == 255
    assert mask[0, 0] == 0
    assert region.style.fill_rgb[0] < 40
    assert region.style.uppercase is True
    assert region.style.alignment == "center"


def test_two_pixel_dot_stays_in_the_mask():
    image = np.full((60, 100, 3), 255, dtype=np.uint8)
    image[30, 50] = 0
    image[30, 51] = 0
    region = TextRegion(id=1, bbox=(20, 12, 60, 36), text="A.")
    mask = segment_region(image, region)
    assert mask[30, 50] == 255
    assert mask[30, 51] == 255


def test_white_letters_on_black_read_as_white():
    image = Image.new("RGB", (120, 60), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 16, 90, 40), fill="white")
    region = TextRegion(id=1, bbox=(10, 8, 100, 44), text="HELLO")
    segment_region(np.array(image), region)
    assert region.style.fill_rgb == (255, 255, 255)


def test_antialiased_black_on_white_has_no_stroke():
    crop = np.full((40, 80, 3), 255, dtype=np.uint8)
    ink = np.zeros((40, 80), dtype=bool)
    ink[10:30, 20:60] = True
    crop[ink] = 0
    crop[9, 20:60] = 213
    crop[30, 20:60] = 213
    crop[10:30, 19] = 213
    crop[10:30, 60] = 213
    background = np.array([255.0, 255.0, 255.0])
    fill, stroke = _colors(crop, ink, background)
    assert fill[0] < 40
    assert stroke is None


def test_colored_outline_stays_a_stroke():
    crop = np.full((40, 80, 3), 255, dtype=np.uint8)
    ink = np.zeros((40, 80), dtype=bool)
    ink[10:30, 20:60] = True
    crop[ink] = 0
    crop[9, 20:60] = (220, 20, 20)
    crop[30, 20:60] = (220, 20, 20)
    crop[10:30, 19] = (220, 20, 20)
    crop[10:30, 60] = (220, 20, 20)
    background = np.array([255.0, 255.0, 255.0])
    _fill, stroke = _colors(crop, ink, background)
    assert stroke is not None
    assert stroke[0] > 180
    assert stroke[1] < 60


def test_segment_region_keeps_font_id_and_warp():
    image = np.full((48, 96, 3), 255, dtype=np.uint8)
    image[16:32, 20:76] = 0
    region = TextRegion(id=1, bbox=(8, 8, 80, 32), text="Hi", block_type="dialogue")
    region.style.font_id = "kept-font"
    region.style.rotation = 15.0
    region.style.stroke_mode = "custom"
    region.style.stroke_width = 4.5
    region.style.warp = {"kind": "arc", "bend": 0.25, "quad": None, "mesh": None}
    segment_region(image, region)
    assert region.style.font_id == "kept-font"
    assert region.style.rotation == 15.0
    assert region.style.stroke_mode == "custom"
    assert region.style.stroke_width == 4.5
    assert region.style.warp["kind"] == "arc"
    assert region.style.warp["bend"] == 0.25
    assert region.style.fill_rgb[0] < 40


def test_dialogue_bubble_mask_stays_inside_the_outline():
    image = Image.new("RGB", (160, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((24, 20, 136, 100), outline="black", width=3)
    region = TextRegion(
        id=1,
        bbox=(60, 45, 40, 30),
        bubble_bbox=(8, 8, 144, 104),
        text="HELLO",
        block_type="dialogue",
    )
    mask = segment_region(np.array(image), region)
    assert mask[60, 80] == 255
    # На обводке / снаружи — без маски; чуть внутри — покрыто (inset=2).
    assert mask[60, 24] == 0
    assert mask[60, 34] == 255
    assert mask[2, 2] == 0
    assert region.style.uppercase is True


def test_sfx_mask_hugs_ink_plus_four_px():
    image = np.full((80, 140, 3), 255, dtype=np.uint8)
    image[30:50, 30:110] = 0
    sfx = TextRegion(id=2, bbox=(16, 16, 108, 48), text="BANG", block_type="sfx")
    mask_sfx = segment_region(image, sfx)

    ink = np.zeros((80, 140), dtype=np.uint8)
    ink[30:50, 30:110] = 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    expected = cv2.dilate(ink, kernel, iterations=1)
    # Маска должна совпадать с dilate(ink, +4px) внутри bbox-кропа (pad=3).
    assert int(mask_sfx.sum()) == int(expected.sum())
    # Старый жирный режим (radius ~ line_height) был заметно больше.
    fat_radius = max(2, int(round(20 * 0.22)))
    fat_radius = max(fat_radius + 2, int(round(fat_radius * 1.6)))
    fat_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (fat_radius * 2 + 1, fat_radius * 2 + 1)
    )
    fat = cv2.dilate(ink, fat_kernel, iterations=1)
    assert int(mask_sfx.sum()) < int(fat.sum())


def test_apply_strokes_paints_and_erases_without_mutating_input():
    mask = np.zeros((20, 20), dtype=np.uint8)
    untouched = apply_strokes(mask, [])
    assert untouched is not mask
    assert np.array_equal(untouched, mask)

    painted = apply_strokes(mask, [
        MaskStroke(mode="paint", radius=2, points=[(5, 5), (8, 5)]),
    ])
    assert int(mask.sum()) == 0
    assert painted[5, 5] == 255
    assert painted[7, 5] == 255

    erased = apply_strokes(painted, [
        MaskStroke(mode="erase", radius=2, points=[(5, 5)]),
    ])
    assert erased[5, 5] == 0
    assert painted[5, 5] == 255

    outside = apply_strokes(mask, [
        MaskStroke(mode="paint", radius=2, points=[(-30, -30), (-20, -28)]),
    ])
    assert outside.shape == mask.shape
    assert int(outside.sum()) == 0
    clipped = apply_strokes(mask, [
        MaskStroke(mode="paint", radius=3, points=[(0, 0)]),
    ])
    assert clipped[0, 0] == 255


def test_apply_strokes_fill_polygon():
    mask = np.zeros((20, 20), dtype=np.uint8)
    filled = apply_strokes(mask, [
        MaskStroke(mode="fill", radius=1, points=[(2, 2), (17, 2), (17, 17), (2, 17)]),
    ])
    assert filled[10, 10] == 255
    assert filled[0, 0] == 0
    assert int(mask.sum()) == 0
    too_few = apply_strokes(mask, [
        MaskStroke(mode="fill", radius=1, points=[(2, 2), (17, 2)]),
    ])
    assert int(too_few.sum()) == 0


def test_apply_strokes_erase_fill_polygon():
    mask = np.full((20, 20), 255, dtype=np.uint8)
    erased = apply_strokes(mask, [
        MaskStroke(mode="erase_fill", radius=1, points=[(2, 2), (17, 2), (17, 17), (2, 17)]),
    ])
    assert erased[10, 10] == 0
    assert erased[0, 0] == 255
    assert int(mask.sum()) == 20 * 20 * 255

def test_apply_strokes_flood_paint_and_erase_in_order():
    image = Image.new("RGB", (10, 10), "white")
    for y in range(10):
        image.putpixel((5, y), (0, 0, 0))
    mask = np.zeros((10, 10), dtype=np.uint8)
    painted = apply_strokes(mask, [
        MaskStroke(mode="flood", radius=0, points=[(1, 1)], tolerance=20),
    ], image)
    assert painted[0, 0] == 255 and painted[0, 4] == 255
    assert painted[0, 9] == 0
    erased = apply_strokes(painted, [
        MaskStroke(mode="erase_flood", radius=0, points=[(9, 9)], tolerance=20),
    ], image)
    assert erased[0, 0] == 255
    assert erased[0, 9] == 0
    no_image = apply_strokes(mask, [
        MaskStroke(mode="flood", radius=0, points=[(1, 1)], tolerance=20),
    ])
    assert int(no_image.sum()) == 0


def test_free_text_on_paper_covers_handwritten_form_lines():
    """Тёмные строки на светлом бланке внутри комикса закрываются ink, не баллоном."""
    rgb = np.full((220, 280, 3), (55, 70, 90), np.uint8)
    rgb[30:170, 25:210] = (248, 244, 232)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    for y, word in [(80, "LINDA"), (125, "NAME")]:
        cv2.putText(rgb, word, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 20, 18), 2)
        cv2.putText(expected, word, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2)
    region = TextRegion(
        1, (35, 50, 165, 95), text="LINDA NAME", block_type="narration", class_name="text_free",
    )
    mask = segment_region(rgb, region)
    assert np.mean(mask[expected > 0] > 0) >= .90
    assert np.count_nonzero(mask[:25]) == 0


def test_contrast_sfx_next_to_balloon_keeps_separate_masks():
    """Контрастный SFX рядом с репликой не входит в маску облачка."""
    rgb = np.full((140, 260, 3), (70, 75, 80), np.uint8)
    cv2.ellipse(rgb, (80, 70), (70, 45), 0, 0, 360, (250, 250, 250), -1)
    cv2.ellipse(rgb, (80, 70), (70, 45), 0, 0, 360, (20, 20, 20), 2)
    expected_hi = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "HI", (52, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (15, 15, 15), 2)
    cv2.putText(expected_hi, "HI", (52, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2)
    expected_ding = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(rgb, "DING", (165, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 6)
    cv2.putText(expected_ding, "DING", (165, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 6)
    cv2.putText(rgb, "DING", (165, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (10, 10, 10), 2)
    cv2.putText(expected_ding, "DING", (165, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
    speech = TextRegion(1, (45, 45, 70, 50), text="HI", block_type="dialogue",
                        bubble_bbox=(8, 22, 145, 95))
    sound = TextRegion(2, (160, 55, 85, 45), text="DING", block_type="sfx")
    balloon = segment_region(rgb, speech)
    sfx = segment_region(rgb, sound)
    assert np.mean(balloon[expected_hi > 0] > 0) >= .90
    assert np.mean(sfx[expected_ding > 0] > 0) >= .70
    assert np.mean(balloon[expected_ding > 0] > 0) < .12


def test_two_tone_light_bubble_covers_every_word_without_outline():
    rgb = np.full((160, 300, 3), (80, 30, 110), np.uint8)
    cv2.rectangle(rgb, (10, 10), (290, 150), (235, 235, 240), -1)
    rgb[10:151, 150:291] = (205, 220, 230)
    cv2.rectangle(rgb, (10, 10), (290, 150), (25, 20, 25), 3)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    for text,y in [('HELLO WORLD',65), ('MORE WORDS',115)]:
        cv2.putText(rgb,text,(25,y),cv2.FONT_HERSHEY_SIMPLEX,.9,(30,20,30),2)
        cv2.putText(expected,text,(25,y),cv2.FONT_HERSHEY_SIMPLEX,.9,255,2)
    r = TextRegion(1,(20,35,260,90),bubble_bbox=(5,5,290,150))
    m = segment_region(rgb,r)
    assert np.mean(m[expected>0]>0)>=.99
    assert m[10,150]==0
