"""Регрессии аудита геометрии, очистки, OCR и вёрстки."""

import copy

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.components.lama_inpainter import LamaInpainter
from src.components.rapid_ocr import OcrWord, RapidOcr
from src.config import Config
from src.errors import PipelineCancelled
from src.models import TextRegion, TextStyle
from src.page_pipeline import PagePipeline, _composite_changes, _scale_regions


def _manual_region() -> TextRegion:
    return TextRegion(
        1,
        (10, 10, 20, 20),
        translation="Привет",
        text_position=(150.0, 130.0),
        style=TextStyle(stroke_width=2.0, letter_spacing=1.0, line_spacing=1.0, font_size=16),
    )


def test_manual_position_and_spacing_scale_with_the_page():
    region = _manual_region()
    region.style.warp = {
        "version": 1,
        "kind": "mesh",
        "bend": 0.0,
        "quad": [[1, 2], [3, 4], [5, 6], [7, 8]],
        "mesh": [[0, 0], [8, 4]],
    }
    _scale_regions([region], 2)
    assert region.bbox == (20, 20, 40, 40)
    assert region.text_position == (300.0, 260.0)
    assert region.style.stroke_width == 4.0
    assert region.style.letter_spacing == 2.0
    assert region.style.line_spacing == 2.0
    assert region.style.font_size == 32
    assert region.style.line_height == 36
    assert region.style.warp["quad"][0] == [2, 4]
    assert region.style.warp["mesh"][1] == [16, 8]
    assert region.layout_snapshot is None


def test_cancelled_typeset_keeps_the_original_geometry():
    image = Image.new("RGB", (100, 80), "white")
    region = _manual_region()
    before = region.to_dict()
    pipeline = PagePipeline(Config(layout_long_side=200, adaptive_text=False))
    with pytest.raises(PipelineCancelled):
        pipeline.typeset_image(image, [region], "ru", cancel_check=lambda: True)
    assert region.to_dict() == before


def test_cancelled_clean_keeps_snapshot_geometry():
    image = Image.new("RGB", (100, 80), "white")
    region = _manual_region()
    region.layout_snapshot = {"version": 1, "font_size": 12, "lines": [["Привет", 12, 14]]}
    before = region.to_dict()
    pipeline = PagePipeline(Config(layout_long_side=200, adaptive_text=False))
    with pytest.raises(PipelineCancelled):
        pipeline.clean(image, [region], cancel_check=lambda: True)
    assert region.to_dict() == before


def _ink_center(image: Image.Image) -> tuple[float, float]:
    dark = np.any(np.asarray(image.convert("RGB")) < 200, axis=2)
    ys, xs = np.nonzero(dark)
    assert len(xs) > 0
    return float(xs.mean()), float(ys.mean())


def test_upscaled_manual_text_matches_native_placement_and_repeats():
    image = Image.new("RGB", (120, 90), "white")
    style = TextStyle(
        font_size_override=18,
        stroke_mode="none",
        letter_spacing=1.0,
        line_spacing=0.0,
    )

    def region() -> TextRegion:
        return TextRegion(
            1,
            (20, 25, 70, 30),
            translation="Hi",
            text_position=(55.0, 40.0),
            manual=True,
            style=copy.deepcopy(style),
        )

    native = PagePipeline(Config(layout_long_side=0, adaptive_text=False))
    scaled = PagePipeline(Config(layout_long_side=240, adaptive_text=False))
    native_image, _ = native.typeset_image(image, [region()], "en")
    sample = region()
    before = sample.to_dict()
    first, _ = scaled.typeset_image(image, [sample], "en")
    assert sample.to_dict()["text_position"] == before["text_position"]
    assert sample.bbox == (20, 25, 70, 30)
    second, _ = scaled.typeset_image(image, [sample], "en")
    assert np.array_equal(np.asarray(first), np.asarray(second))
    native_center = _ink_center(native_image)
    scaled_center = _ink_center(first)
    assert abs(native_center[0] - scaled_center[0]) < 4
    assert abs(native_center[1] - scaled_center[1]) < 4


def test_empty_clean_keeps_every_source_pixel():
    source = np.arange(80 * 100 * 3, dtype=np.uint8).reshape(80, 100, 3)
    image = Image.fromarray(source)
    region = TextRegion(1, (10, 10, 20, 20))
    before = region.to_dict()
    pipeline = PagePipeline(Config(layout_long_side=200, adaptive_text=False))
    _mask, cleaned = pipeline.clean(image, [region])
    assert np.array_equal(np.array(cleaned), source)
    assert region.to_dict() == before


def test_cleanup_changes_do_not_repaint_the_rest_of_the_page():
    source = np.zeros((40, 60, 3), dtype=np.uint8)
    source[:] = np.arange(60, dtype=np.uint8)[None, :, None]
    page = Image.fromarray(source, "RGB")
    work = page.resize((120, 80), Image.Resampling.LANCZOS)
    produced = work.copy()
    painted = np.array(produced)
    painted[20:36, 30:50] = 255
    produced = Image.fromarray(painted, "RGB")
    result = np.array(_composite_changes(page, work, produced))
    assert np.array_equal(result[:8, :8], source[:8, :8])
    assert np.array_equal(result[:, 55:], source[:, 55:])
    assert np.any(result != source)

    class RedFill:
        def inpaint(self, image, mask, allow_flat_fill=True):
            canvas = np.array(image.convert("RGB"))
            canvas[np.asarray(mask) > 0] = (255, 0, 0)
            return Image.fromarray(canvas, "RGB")

    drawn = np.array(page)
    drawn[16:24, 20:36] = 0
    page = Image.fromarray(drawn, "RGB")
    region = TextRegion(1, (18, 14, 20, 12), text="Hi", translation="Да")
    pipeline = PagePipeline(Config(layout_long_side=120, adaptive_text=False), inpainter=RedFill())
    _mask, cleaned = pipeline.clean(page, [region])
    cleaned_rgb = np.array(cleaned)
    assert np.array_equal(cleaned_rgb[:4, :4], drawn[:4, :4])
    assert np.array_equal(cleaned_rgb[:, 52:], drawn[:, 52:])


def test_rapid_ocr_keeps_short_upper_word_before_tall_lower_word():
    ocr = RapidOcr()
    ocr._words = lambda _image: [
        OcrWord("BOTTOM", (10, 40, 50, 40), 0.9),
        OcrWord("TOP", (10, 20, 30, 10), 0.9),
    ]
    region = TextRegion(1, (0, 0, 120, 100))
    ocr.read_crop(Image.new("RGB", (120, 100), "white"), region)
    assert region.text == "TOP BOTTOM"


def test_screentone_ring_is_not_a_flat_fill():
    image = np.full((80, 80, 3), 255, dtype=np.uint8)
    image[::4, ::4] = 0
    component = np.zeros((80, 80), dtype=np.uint8)
    component[30:50, 30:50] = 255
    inpainter = LamaInpainter(device="cpu")
    assert inpainter._fill_if_uniform(image, component, component) is False


def test_pipeline_keeps_configured_font_limits():
    pipeline = PagePipeline(Config(min_font_size=8, max_font_size=48))
    assert pipeline.typesetter.min_font_size == 8
    assert pipeline.typesetter.max_font_size == 48


def _open_balloon():
    """Белый баллон и бокс текста, вылезающий на чёрный рисунок справа."""
    image = Image.new("RGB", (220, 280), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 20, 130, 260), fill=(250, 250, 250))
    draw.rectangle((80, 130, 96, 152), fill=(0, 0, 0))
    region = TextRegion(
        id=1,
        bbox=(70, 120, 100, 40),
        bubble_bbox=(30, 20, 100, 240),
        text="Hello",
        translation="Привет",
        block_type="dialogue",
        class_name="text_bubble",
    )
    return np.array(image), region


def test_failed_silhouette_masks_letters_inside_balloon(monkeypatch):
    monkeypatch.setattr(
        "src.components.text_segmenter.bubble_interior_mask",
        lambda *_args, **_kwargs: np.zeros((280, 220), np.uint8),
    )
    image, region = _open_balloon()
    from src.components.text_segmenter import segment_region

    mask = segment_region(image, region)
    assert mask[140, 88] > 0
    assert mask[140, 160] == 0
    assert int(np.sum(mask[:, 130:])) == 0


def test_letter_grow_widens_ink_by_one_pixel():
    import cv2
    from src.components.text_segmenter import segment_region

    image = Image.new("RGB", (80, 40), (200, 30, 30))
    ImageDraw.Draw(image).rectangle((20, 10, 40, 28), fill=(0, 0, 0))
    region = TextRegion(1, (16, 6, 30, 28), text="A", block_type="sfx")
    rgb = np.array(image)
    base = segment_region(rgb, region, letter_grow_px=0)
    grown = segment_region(rgb, region, letter_grow_px=1)
    assert int(np.sum(grown > 0)) > int(np.sum(base > 0))
    assert np.all((base > 0) <= (grown > 0))
    outside = cv2.distanceTransform((base == 0).astype(np.uint8), cv2.DIST_L2, 3)
    extra = (grown > 0) & (base == 0)
    assert float(outside[extra].max()) <= 1.5


def test_letter_grow_does_not_expand_balloon_silhouette(monkeypatch):
    from src.components.text_segmenter import segment_region

    sentinel = np.zeros((40, 60), np.uint8)
    sentinel[4:36, 4:56] = 255
    monkeypatch.setattr(
        "src.components.text_segmenter.bubble_interior_mask",
        lambda *_args, **_kwargs: sentinel,
    )
    image = np.full((40, 60, 3), 255, np.uint8)
    region = TextRegion(
        1, (10, 10, 20, 16), text="Hi", bubble_bbox=(2, 2, 56, 36), block_type="dialogue",
    )
    assert np.array_equal(
        segment_region(image, region, letter_grow_px=0),
        segment_region(image, region, letter_grow_px=1),
    )
