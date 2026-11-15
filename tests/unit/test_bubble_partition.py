"""Соседние реплики внутри одного детекторного бокса остаются независимыми."""

import cv2
import numpy as np
from PIL import Image

from src.components.bubble_partition import partition_area, partition_retouch_area, split_balloon_regions
from src.components.vlm_ocr import VlmOcr
from src.components.typesetter import Typesetter
from src.models import TextRegion


def _scene(second=True):
    rgb = np.zeros((160, 320, 3), np.uint8)
    cv2.rectangle(rgb, (5, 5), (310, 100), (255, 255, 255), -1)
    cv2.putText(rgb, 'FIRST SPEAKER', (20, 45), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    cv2.putText(rgb, 'ANOTHER LINE', (20, 78), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    if second:
        cv2.rectangle(rgb, (60, 105), (305, 150), (255, 255, 255), -1)
        cv2.putText(rgb, 'SECOND VOICE', (75, 133), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    return Image.fromarray(rgb), TextRegion(id=1, bbox=(18, 25, 280, 113), bubble_bbox=(3, 3, 310, 150))


def test_two_enclosed_texts_split_with_disjoint_persistent_geometry():
    image, region = _scene()
    parts = split_balloon_regions(image, [region])
    assert len(parts) == 2
    masks = [partition_area((160, 320), TextRegion.from_dict(r.to_dict())) for r in parts]
    assert not np.any((masks[0] > 0) & (masks[1] > 0))
    assert all(np.count_nonzero(mask) > 1000 for mask in masks)


def test_single_balloon_and_existing_text_are_preserved():
    image, region = _scene(False)
    assert split_balloon_regions(image, [region]) == [region]
    image, region = _scene()
    region.text = 'Already recognized'
    assert split_balloon_regions(image, [region]) == [region]
    region.text = ''
    region.manual = True
    assert split_balloon_regions(image, [region]) == [region]


def test_partition_ocr_reads_only_its_own_body():
    image, region = _scene()
    parts = split_balloon_regions(image, [region])

    class Client:
        def chat_json(self, **kwargs):
            crop = np.asarray(kwargs['images'][0])
            # Поле после первой реплики не содержит соседнего текста.
            assert np.all(crop[-5:] == 255)
            return {'text': 'FIRST SPEAKER ANOTHER LINE', 'type': 'dialogue'}

    assert VlmOcr(Client()).read_crop(image, parts[0]) == 'FIRST SPEAKER ANOTHER LINE'


def test_white_letter_outlines_are_not_separate_balloons():
    rgb = np.full((100, 300, 3), (30, 80, 70), np.uint8)
    for y in (35, 75):
        cv2.putText(rgb, 'OUTLINED TEXT', (12, y), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 8)
        cv2.putText(rgb, 'OUTLINED TEXT', (12, y), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    region = TextRegion(id=1, bbox=(10, 15, 270, 65), bubble_bbox=(0, 0, 300, 100))
    assert split_balloon_regions(Image.fromarray(rgb), [region]) == [region]


def test_translation_respects_separator_after_scaling_and_reload():
    from src.page_pipeline import _scale_regions

    image, region = _scene()
    parts = split_balloon_regions(image, [region])
    _scale_regions(parts, 2.)
    parts = [TextRegion.from_dict(p.to_dict()) for p in parts]
    for part in parts:
        part.translation = 'Разные реплики остаются раздельными'
    blank = Image.new('RGB', (640, 320), 'white')
    rendered, overflow = Typesetter(min_font_size=8, max_font_size=28, font_scale=1.).render(blank, parts)
    assert not overflow
    allowed = np.maximum(*(partition_area((320, 640), p) for p in parts))
    changed = np.min(np.asarray(rendered), axis=2) < 200
    assert changed.any()
    assert not np.any(changed & (allowed == 0))


def test_attached_letter_is_cleaned_without_erasing_separator():
    image, region = _scene(False)
    rgb = np.array(image)
    cv2.putText(rgb, 'A', (220, 101), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 2)
    body = (rgb.min(axis=2) > 210).astype(np.uint8)*255
    contours, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(body, contours, -1, 255, -1)
    repaired = partition_retouch_area(rgb, region, body)
    assert np.count_nonzero((repaired > 0) & (body == 0)) > 20
    assert not np.any(repaired[102:])
