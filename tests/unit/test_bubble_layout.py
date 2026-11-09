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


def test_caption_neighbors_use_measured_fields_instead_of_shared_balloon_box():
    """Ошибочная общая рамка карточек не режет свободное поле соседней реплики."""
    from src.components.bubble_layout import separate_neighbour_bubbles
    first = TextRegion(1, (40, 40, 200, 40), translation='Первая реплика',
                       bubble_bbox=(0, 0, 400, 300),
                       auto_layout=dict(version=1, kind='free', readable_caption=True, ink_bbox=[30, 20, 220, 110]))
    second = TextRegion(2, (40, 150, 200, 40), translation='Вторая реплика',
                        bubble_bbox=(0, 0, 400, 300),
                        auto_layout=dict(version=1, kind='free', readable_caption=True, ink_bbox=[30, 140, 220, 80]))
    mask = np.zeros((300, 400), np.uint8)
    mask[20:130, 30:250] = 255
    result = separate_neighbour_bubbles(mask, first, [first, second])
    assert np.array_equal(result, mask)


def test_translucent_colour_layout_crosses_background_panel():
    from src.components.bubble_layout import colour_layout_area

    image = np.full((140, 200, 3), 250, np.uint8)
    oval = np.zeros((140, 200), np.uint8)
    cv2.ellipse(oval, (100, 70), (80, 50), 0, 0, 360, 255, -1)
    image[oval > 0] = (160, 197, 237)
    panel = (oval > 0) & (np.indices(oval.shape)[1] > 115)
    image[panel] = (114, 131, 173)
    cv2.putText(image, 'HELLO', (52, 78), cv2.FONT_HERSHEY_SIMPLEX, .65, (20, 20, 20), 2)
    region = TextRegion(1, (45, 45, 110, 50), bubble_bbox=(18, 18, 164, 104))
    partial = oval.copy()
    partial[:, 115:] = 0
    result = colour_layout_area(image, region, partial)
    assert np.mean(result[oval > 0] > 0) > .98
    assert not np.any(result[oval == 0])
    assert np.array_equal(colour_layout_area(image, region, oval), oval)


def test_colour_layout_rejects_background_leaking_through_box():
    from src.components.bubble_layout import colour_layout_area

    image = np.full((140, 200, 3), (160, 197, 237), np.uint8)
    region = TextRegion(1, (45, 45, 110, 50), bubble_bbox=(18, 18, 164, 104))
    fallback = np.zeros((140, 200), np.uint8)
    fallback[45:95, 45:155] = 255
    assert np.array_equal(colour_layout_area(image, region, fallback), fallback)


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


def test_shape_layout_uses_wide_body_above_long_narrow_tail():
    """Хвост сдвигает общий центр, но не должен вытеснять текст из тела."""
    mask = np.zeros((320, 250), np.uint8)
    mask[10:110, 20:230] = 255
    mask[110:310, 115:135] = 255
    region = TextRegion(1, (30, 20, 180, 70))
    font = _load_font(_font_file(region), 22)
    draw = ImageDraw.Draw(Image.new('RGB', (250, 320)))
    text = 'ПОЛНЫЙ ТЕКСТ РЕПЛИКИ'
    placed, fits = layout_in_shape(text, font, draw, _row_spans(mask), None, 'center')
    assert fits
    assert ' '.join(line for line, _, _ in placed) == text
    for line, x, y in placed:
        left, top, right, bottom = draw.textbbox((x, y), line, font=font)
        assert bottom <= 110
        assert np.all(mask[top:bottom, left:right] > 0)


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


def _ellipse_region(region_id, center, axes, translation, canvas):
    mask = np.zeros(canvas, np.uint8)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
    ys, xs = np.nonzero(mask)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    region = TextRegion(
        region_id, bbox, translation=translation, bubble_bbox=None,
        auto_layout={'version': 1, 'kind': 'bubble'},
    )
    return mask, region


def test_inferred_neighbour_bubbles_split_overlap_by_centroid():
    """Без bubble_bbox пересекающиеся маски режутся по центроиду, глифы не слипаются."""
    from src.components.bubble_layout import separate_neighbour_bubbles
    from src.components.typesetter import Typesetter

    canvas = (220, 420)
    left_mask, left = _ellipse_region(1, (150, 110), (120, 80), "Эй, Рарити!", canvas)
    right_mask, right = _ellipse_region(2, (280, 115), (125, 85), "Какие кроссовки.", canvas)
    assert np.any((left_mask > 0) & (right_mask > 0))
    lx, ly, lw, lh = left.bbox
    rx, ry, rw, rh = right.bbox
    assert min(lx + lw, rx + rw) > max(lx, rx) and min(ly + lh, ry + rh) > max(ly, ry)
    a = separate_neighbour_bubbles(left_mask, left, [left, right])
    b = separate_neighbour_bubbles(right_mask, right, [left, right])
    assert not np.any((a > 0) & (b > 0))
    image = Image.new('RGB', (canvas[1], canvas[0]), (30, 30, 30))
    setter = Typesetter(min_font_size=10, max_font_size=48, font_scale=1.0, lang='ru')
    setter.render(image, [left, right])
    draw = ImageDraw.Draw(Image.new('RGB', (canvas[1], canvas[0])))
    boxes = []
    for region_id in (1, 2):
        layout = setter._last_layouts[region_id]
        font = _load_font(_font_file(left if region_id == 1 else right), layout['font_size'])
        union = None
        for line, x, y in layout['lines']:
            box = draw.textbbox((x, y), line, font=font)
            union = box if union is None else (
                min(union[0], box[0]), min(union[1], box[1]),
                max(union[2], box[2]), max(union[3], box[3]),
            )
        boxes.append(union)
    left_box, right_box = boxes
    assert left_box[2] <= right_box[0] or right_box[2] <= left_box[0] or left_box[3] <= right_box[1] or right_box[3] <= left_box[1]


def test_single_inferred_bubble_with_two_lines_is_not_bisected():
    """Одно облачко из двух строк остаётся целой маской."""
    from src.components.bubble_layout import separate_neighbour_bubbles

    mask, region = _ellipse_region(1, (160, 110), (140, 85), "Первая строка вторая", (220, 320))
    assert np.array_equal(separate_neighbour_bubbles(mask, region, [region]), mask)


def test_separated_tails_do_not_form_a_wide_line():
    from src.components.bubble_layout import shape_row_spans

    mask = np.zeros((20, 100), np.uint8)
    mask[:10, 10:90] = 255
    mask[10:, 10:13] = 255
    mask[10:, 87:90] = 255
    spans = shape_row_spans(mask)
    assert spans[5] == (10, 89)
    assert spans[15][1] - spans[15][0] == 2


def test_translucent_window_oval_centers_translation_in_ellipse():
    from src.components.adaptive_text import prepare_regions
    from src.components.bubble_layout import (
        bbox_ellipse_layout_area, colour_layout_area, covers_source, light_layout_area,
    )
    from src.components.typesetter import Typesetter, interior_mask
    from src.models import TextStyle

    height, width = 220, 320
    xs = np.linspace(175, 245, width, dtype=np.float32)
    ys = np.linspace(165, 235, height, dtype=np.float32)
    glow = (xs[None, :] + ys[:, None]) / 2
    image = np.stack([glow, glow * 0.97, glow * 0.88], axis=-1)
    image = np.clip(image + (np.indices((height, width))[0] % 9)[:, :, None] * 6, 0, 255).astype(np.uint8)
    oval = np.zeros((height, width), np.uint8)
    center, axes = (160, 110), (95, 58)
    cv2.ellipse(oval, center, axes, 0, 0, 360, 255, -1)
    cyan = np.array([88, 205, 215], np.float32)
    blended = image.astype(np.float32)
    blended[oval > 0] = 0.2 * cyan + 0.8 * blended[oval > 0]
    image = blended.astype(np.uint8)
    cv2.putText(image, 'HELLO', (112, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (15, 15, 15), 2)
    region = TextRegion(
        1, (108, 90, 105, 40), text='HELLO', translation='Привет всем вокруг',
        bubble_bbox=(62, 50, 196, 120), block_type='dialogue',
        style=TextStyle(stroke_mode='none'),
    )
    letter_box = np.zeros((height, width), np.uint8)
    x, y, w, h = region.bbox
    letter_box[y:y + h, x:x + w] = 255
    assert np.array_equal(colour_layout_area(image, region, letter_box), letter_box)
    assert np.array_equal(light_layout_area(image, region, letter_box), letter_box)
    oval_area = bbox_ellipse_layout_area(region, letter_box)
    assert covers_source(oval_area, region)
    assert np.count_nonzero(oval_area) > np.count_nonzero(letter_box) * 1.5
    page = Image.fromarray(image)
    prepare_regions(page, [region])
    area = interior_mask(image, region)
    assert np.mean(area[oval > 0] > 0) > 0.85
    result, overflow = Typesetter(min_font_size=10, max_font_size=42).render(page, [region])
    assert not overflow
    ink = np.asarray(result).min(axis=2) < 80
    ys, xs = np.where(ink)
    assert len(xs)
    assert abs(float(xs.mean()) - center[0]) <= 18
    assert abs(float(ys.mean()) - center[1]) <= 16
    assert region.style.rotation == 0
