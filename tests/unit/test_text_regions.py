"""Слияние строк, привязка к баллону и порядок чтения."""

from src.components.bubble_detector import Detection
from src.components.text_regions import (
    build_regions,
    can_merge_collinear,
    can_merge_paragraph,
    merge_collinear,
    merge_columns,
)
from src.models import TextRegion


def _text(box, class_name="text_free", confidence=0.9):
    class_id = 1 if class_name == "text_bubble" else 2
    return Detection(box, class_id, class_name, confidence)


def _bubble(box):
    return Detection(box, 0, "bubble", 0.9)


def test_lines_inside_one_bubble_merge():
    regions = build_regions([
        _bubble((0, 0, 100, 80)),
        _text((10, 10, 70, 18), "text_bubble"),
        _text((10, 34, 70, 18), "text_bubble"),
    ])
    assert len(regions) == 1
    assert regions[0].bubble_bbox == (0, 0, 100, 80)
    assert regions[0].bbox[1] == 10
    assert regions[0].block_type == "dialogue"


def test_paragraph_lines_merge_and_distant_lines_stay():
    close_a = TextRegion(id=1, bbox=(10, 10, 200, 20), bubble_bbox=None)
    close_b = TextRegion(id=2, bbox=(10, 34, 200, 20), bubble_bbox=None)
    assert can_merge_paragraph(close_a, close_b)
    far = TextRegion(id=3, bbox=(10, 90, 200, 20), bubble_bbox=None)
    assert not can_merge_paragraph(close_b, far)

    regions = build_regions([
        _text((10, 10, 200, 20)),
        _text((12, 34, 200, 20)),
        _text((10, 120, 200, 20)),
    ])
    assert len(regions) == 2


def test_document_column_merges_but_title_and_wide_line_stay():
    regions = merge_columns([
        TextRegion(id=1, bbox=(41, 29, 361, 54)),
        TextRegion(id=2, bbox=(41, 113, 440, 97)),
        TextRegion(id=3, bbox=(41, 226, 454, 97)),
        TextRegion(id=4, bbox=(41, 340, 453, 154)),
        TextRegion(id=5, bbox=(41, 510, 278, 40)),
        TextRegion(id=6, bbox=(41, 601, 948, 161)),
    ])
    assert len(regions) == 3
    widths = sorted(region.bbox[2] for region in regions)
    assert widths[0] == 361
    assert widths[-1] == 948


def test_lower_bubble_stays_below():
    regions = build_regions([
        _bubble((70, 690, 110, 90)),
        _text((80, 701, 86, 70), "text_bubble"),
        _bubble((90, 530, 160, 150)),
        _text((111, 548, 110, 112), "text_bubble"),
        _bubble((400, 570, 170, 190)),
        _text((424, 628, 117, 115), "text_bubble"),
    ])
    assert [region.bbox[1] for region in regions] == [548, 628, 701]


def test_page_sized_box_is_dropped():
    from src.components.text_regions import filter_detections

    kept = filter_detections(
        [
            _text((0, 0, 1000, 800)),
            _text((10, 10, 120, 40)),
        ],
        (1000, 800),
    )
    assert len(kept) == 1
    assert kept[0].bbox == (10, 10, 120, 40)


def test_collinear_slanted_fragments_merge_even_if_types_differ():
    """Два наклонных AABB одной фразы сливаются; два баллона — нет."""
    left = TextRegion(1, bbox=(20, 40, 160, 50), block_type="sfx")
    right = TextRegion(2, bbox=(165, 58, 90, 48), block_type="dialogue")
    assert can_merge_collinear(left, right)
    merged = merge_collinear([left, right])
    assert len(merged) == 1
    assert merged[0].bbox == (20, 40, 235, 66)
    two_bubbles = [
        TextRegion(3, bbox=(20, 40, 160, 50), bubble_bbox=(10, 30, 180, 70)),
        TextRegion(4, bbox=(165, 58, 90, 48), bubble_bbox=(160, 50, 110, 70)),
    ]
    assert not can_merge_collinear(two_bubbles[0], two_bubbles[1])
    assert len(merge_collinear(two_bubbles)) == 2
    distant = TextRegion(5, bbox=(20, 40, 200, 80))
    other = TextRegion(6, bbox=(280, 200, 160, 70))
    assert not can_merge_collinear(distant, other)


def test_rtl_puts_the_right_box_first():
    regions = build_regions(
        [
            _text((10, 10, 30, 20)),
            _text((80, 10, 30, 20)),
        ],
        reading_order="rtl",
    )
    assert [region.bbox[0] for region in regions] == [80, 10]
    assert regions[0].order == 0
