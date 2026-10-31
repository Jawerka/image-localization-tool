"""Прямоугольники документов не теряют текст и не становятся комиксовыми облачками."""

import numpy as np
from PIL import Image, ImageDraw

from src.components.document_layout import is_document_page, layout_rectangle
from src.components.font_catalog import role_font_id
from src.components.typesetter import _font_file, _load_font, _row_spans
from src.models import TextRegion


def test_document_flag_round_trip_and_font_role():
    region = TextRegion(1, (10, 10, 220, 120), document=True)
    assert TextRegion.from_dict(region.to_dict()).document
    assert not TextRegion.from_dict({"id": 1, "bbox": [1, 1, 20, 20]}).document
    assert role_font_id(region) is None


def test_document_geometry_and_font_ignore_legacy_bubble_box():
    from src.components.typesetter import interior_mask

    plain = TextRegion(1, (10, 10, 40, 30), document=True)
    legacy = TextRegion(1, plain.bbox, document=True, bubble_bbox=(0, 0, 100, 100))
    rgb = np.full((100, 100, 3), 255, np.uint8)
    assert np.array_equal(interior_mask(rgb, plain), interior_mask(rgb, legacy))
    assert _font_file(legacy) == _font_file(plain)


def test_rectangular_paragraph_is_complete_and_inside():
    region = TextRegion(1, (10, 10, 300, 180), document=True)
    font = _load_font(_font_file(region), 24)
    canvas = Image.new("L", (330, 210))
    draw = ImageDraw.Draw(canvas)
    area = np.zeros((210, 330), np.uint8)
    area[10:190, 10:310] = 255
    text = "Перевод абзаца должен целиком помещаться в исходный прямоугольник и сохранять все слова."
    lines, fits = layout_rectangle(
        text, font, draw, _row_spans(area), None, "left", stroke_pad=2
    )
    assert fits and " ".join(s for s, _, _ in lines) == text
    for line, x, y in lines:
        draw.text((x, y), line, font=font, fill=255, stroke_width=2, stroke_fill=255)
    assert not np.any((np.array(canvas) > 0) & (area == 0))
    assert min(y + font.getbbox(line)[1] for line, _, y in lines) <= 15


def test_comic_with_only_small_free_caption_is_not_document():
    rgb = np.full((500, 400, 3), 255, np.uint8)
    assert not is_document_page(rgb, [TextRegion(1, (10, 10, 100, 30))])


def test_document_mask_never_erases_outside_text_box():
    from src.components.text_segmenter import segment_region

    rgb = np.full((100, 160, 3), 255, np.uint8)
    rgb[30:55, 32:38] = 0
    rgb[30:55, 91:97] = 0
    rgb[30:55, 101:104] = 0
    region = TextRegion(1, (30, 25, 70, 40), document=True, bubble_bbox=(0, 0, 160, 100))
    mask = segment_region(rgb, region)
    assert np.any(mask[30:55, 32:38])
    mask[25:65, 30:100] = 0
    assert not np.any(mask)


def test_document_long_url_preserves_every_character_and_stays_inside():
    region = TextRegion(1, (10, 10, 140, 240), document=True)
    font = _load_font(_font_file(region), 20)
    canvas = Image.new("L", (180, 270))
    draw = ImageDraw.Draw(canvas)
    area = np.zeros((270, 180), np.uint8)
    area[10:250, 10:150] = 255
    text = "https://example.com/abcdefghijklmnopqrstuvwxyz0123456789"
    lines, fits = layout_rectangle(text, font, draw, _row_spans(area), None, "left", stroke_pad=2)
    assert fits
    assert "".join(line for line, _, _ in lines) == text
    for line, x, y in lines:
        draw.text((x, y), line, font=font, fill=255, stroke_width=2, stroke_fill=255)
    assert not np.any((np.array(canvas) > 0) & (area == 0))
