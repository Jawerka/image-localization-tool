"""Привязка VLM OCR к цветным рамкам и проверка кропом."""

from PIL import Image

from src.components.vlm_ocr import VlmOcr, _assign_colors, draw_marked_page
from src.models import TextRegion
from src.page_pipeline import PagePipeline


class _Client:
    def __init__(self, pages, crops):
        self.pages = list(pages)
        self.crops = list(crops)
        self.page_prompts = []
        self.page_sizes = []
        self.crop_calls = 0

    def chat_json(self, prompt, schema, schema_name, images, max_tokens=4096):
        del schema, max_tokens
        if schema_name == "crop_ocr":
            self.crop_calls += 1
            return self.crops.pop(0)
        self.page_prompts.append(prompt)
        self.page_sizes.append(images[0].size)
        return self.pages.pop(0)


def _page(blocks, direction="ltr"):
    return {
        "reading_direction": direction,
        "order": [block["id"] for block in blocks],
        "blocks": blocks,
    }


def _block(region_id, text, block_type="dialogue"):
    return {"id": region_id, "text": text, "type": block_type}


def _crop(text, block_type="dialogue"):
    return {"text": text, "type": block_type}


def _region(region_id, bbox, bubble=False, confidence=1.0):
    return TextRegion(
        id=region_id,
        bbox=bbox,
        confidence=confidence,
        bubble_bbox=bbox if bubble else None,
    )


def test_marked_page_is_scaled_and_prompt_uses_zero_to_thousand():
    image = Image.new("RGB", (200, 100), "white")
    regions = [
        _region(1, (0, 0, 100, 50), bubble=True),
        _region(2, (104, 0, 40, 40), bubble=True),
    ]
    marked = draw_marked_page(image, regions, max_side=80)
    assert marked.size == (80, 40)

    client = _Client(
        pages=[_page([_block(1, "ONE"), _block(2, "TWO")])],
        crops=[_crop("ONE"), _crop("TWO")],
    )
    VlmOcr(client, max_side=80).recognize(image, regions)
    assert client.page_sizes == [(80, 40)]
    prompt = client.page_prompts[0]
    assert "1 (red): [0, 0, 500, 500]" in prompt
    assert "2 (blue): [520, 0, 720, 400]" in prompt
    assert "0-1000" in prompt
    assert "Do not renumber" in prompt
    assert "even if ALL CAPS" in prompt
    assert "not ordinary balloon speech" in prompt


def test_neighbors_get_different_colors_and_far_boxes_reuse():
    regions = [
        _region(1, (0, 0, 50, 50)),
        _region(2, (52, 0, 50, 50)),
        _region(3, (0, 150, 50, 50)),
        _region(4, (10, 10, 20, 20)),
    ]
    colors = _assign_colors(regions, (200, 200))
    assert colors[1][0] != colors[2][0]
    assert colors[1][0] != colors[4][0]
    assert colors[3][0] == colors[1][0]


def test_bubble_and_free_text_go_to_separate_passes():
    image = Image.new("RGB", (200, 200), "white")
    regions = [
        _region(1, (0, 0, 40, 40), bubble=True),
        _region(2, (80, 0, 40, 40), bubble=True),
        _region(3, (0, 120, 40, 40)),
        _region(4, (80, 120, 40, 40)),
    ]
    client = _Client(
        pages=[
            _page([_block(1, "B1"), _block(2, "B2")]),
            _page([_block(3, "F1"), _block(4, "F2")]),
        ],
        crops=[_crop("B1"), _crop("B2"), _crop("F1"), _crop("F2")],
    )
    ocr = VlmOcr(client)
    direction, recognized = ocr.recognize(image, regions)
    assert direction == "ltr"
    assert client.crop_calls == 4
    assert "3 (" not in client.page_prompts[0]
    assert "1 (" not in client.page_prompts[1]
    assert [region.text for region in recognized] == ["B1", "B2", "F1", "F2"]
    assert ocr.warnings == []


def test_shifted_ids_reread_only_the_broken_pass():
    image = Image.new("RGB", (200, 200), "white")
    regions = [
        _region(1, (0, 0, 30, 30), bubble=True),
        _region(2, (50, 0, 30, 30), bubble=True),
        _region(3, (100, 0, 30, 30), bubble=True),
        _region(4, (0, 140, 30, 30)),
        _region(5, (80, 140, 30, 30)),
    ]
    client = _Client(
        pages=[
            _page([
                _block(1, "CHARLIE"),
                _block(2, "ALPHA"),
                _block(3, "BRAVO"),
            ]),
            _page([_block(4, "FREE1"), _block(5, "FREE2")]),
        ],
        crops=[
            _crop("ALPHA"),
            _crop("ALPHA"),
            _crop("BRAVO"),
            _crop("CHARLIE"),
            _crop("FREE1"),
            _crop("FREE2"),
        ],
    )
    ocr = VlmOcr(client)
    ocr.recognize(image, regions)
    assert [region.text for region in regions] == ["ALPHA", "BRAVO", "CHARLIE", "FREE1", "FREE2"]
    assert client.crop_calls == 6
    assert ocr.warnings == ["VLM перепутал номера рамок (баллоны), текст дочитан по кропам"]


def test_matching_page_does_not_reread_the_whole_pass():
    image = Image.new("RGB", (200, 80), "white")
    regions = [
        _region(1, (0, 0, 40, 40), bubble=True),
        _region(2, (80, 0, 40, 40), bubble=True),
    ]
    client = _Client(
        pages=[_page([_block(1, "YES"), _block(2, "NO")])],
        crops=[_crop("YES"), _crop("NO")],
    )
    ocr = VlmOcr(client)
    ocr.recognize(image, regions)
    assert client.crop_calls == 2
    assert ocr.warnings == []
    assert [region.text for region in regions] == ["YES", "NO"]


def test_duplicate_text_is_reread_only_for_those_ids():
    image = Image.new("RGB", (240, 80), "white")
    regions = [
        _region(1, (0, 0, 30, 30), bubble=True),
        _region(2, (40, 0, 30, 30), bubble=True),
        _region(3, (160, 0, 30, 30), bubble=True),
    ]
    client = _Client(
        pages=[_page([
            _block(1, "HELLO"),
            _block(2, "HELLO"),
            _block(3, "BYE"),
        ])],
        crops=[_crop("LEFT"), _crop("MID"), _crop("LEFT"), _crop("BYE")],
    )
    ocr = VlmOcr(client)
    ocr.recognize(image, regions)
    assert [region.text for region in regions] == ["LEFT", "MID", "BYE"]
    assert client.crop_calls == 4
    assert ocr.warnings == []


def test_reading_direction_rtl_sets_geometric_order():
    image = Image.new("RGB", (200, 80), "white")
    left = _region(1, (10, 10, 30, 30), bubble=True)
    right = _region(2, (140, 10, 30, 30), bubble=True)
    client = _Client(
        pages=[_page([_block(1, "L"), _block(2, "R")], direction="rtl")],
        crops=[_crop("L"), _crop("R")],
    )
    direction, _regions = VlmOcr(client).recognize(image, [left, right])
    assert direction == "rtl"
    assert right.order < left.order


def test_single_region_is_read_from_crop():
    image = Image.new("RGB", (80, 80), "white")
    region = _region(7, (10, 10, 40, 40), bubble=True)
    client = _Client(pages=[], crops=[_crop("CREEK", "sfx")])
    VlmOcr(client).recognize(image, [region])
    assert client.page_prompts == []
    assert region.text == "CREEK"
    assert region.block_type == "dialogue"


def test_free_crop_may_stay_sfx():
    image = Image.new("RGB", (80, 80), "white")
    region = _region(8, (10, 10, 40, 40), bubble=False)
    client = _Client(pages=[], crops=[_crop("BOOM", "sfx")])
    VlmOcr(client).recognize(image, [region])
    assert region.text == "BOOM"
    assert region.block_type == "sfx"


def test_pipeline_forwards_ocr_warnings():
    class _Ocr:
        warnings = ["VLM перепутал номера рамок (баллоны), текст дочитан по кропам"]

        def recognize(self, image, regions, reading_order="auto"):
            del image, reading_order
            return "ltr", regions

    warnings = []
    PagePipeline(ocr=_Ocr())._recognize(Image.new("RGB", (8, 8)), [], warnings)
    assert warnings == ["VLM перепутал номера рамок (баллоны), текст дочитан по кропам"]
