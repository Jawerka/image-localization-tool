"""PagePipeline на моках OCR и перевода, без LLM и без детектора."""

import json

from PIL import Image, ImageDraw

from src.config import Config
from src.components.bubble_detector import Detection
from src.models import TextRegion
from src.page_pipeline import PagePipeline


class FakeDetector:
    def detect(self, image):
        return [
            Detection((16, 16, 168, 88), 0, "bubble", 0.95),
            Detection((36, 40, 90, 28), 1, "text_bubble", 0.9),
        ]


class FakeOcr:
    def recognize(self, image, regions, reading_order="auto"):
        for region in regions:
            region.text = "Hello"
            region.block_type = "dialogue"
        return "ltr", regions


class FakeTranslator:
    def translate(self, image, regions, source_lang, target_lang, glossary=None, translate_sfx=False):
        for region in regions:
            if region.text:
                region.translation = "Привет"
                region.speaker = "Кирби"
                region.speaker_gender = "male"
        return regions

    def shorten(self, text, target_lang="", max_chars=0, **kwargs):
        return text


def test_page_pipeline_writes_translation(tmp_path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (200, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 184, 104), outline="black", width=2)
    draw.text((48, 48), "HELLO", fill="black")
    image.save(source)

    config = Config(inpainter_backend="opencv", ocr_backend="rapid", translator_backend="argos")
    pipeline = PagePipeline(
        config,
        detector=FakeDetector(),
        ocr=FakeOcr(),
        translator=FakeTranslator(),
    )
    debug = tmp_path / "debug"
    result = pipeline.process(str(source), source_lang="en", target_lang="ru", debug_dir=debug)
    output = tmp_path / "out.png"
    result.save(str(output))
    assert output.exists()
    assert result.regions[0].translation == "Привет"
    assert result.regions[0].speaker == "Кирби"
    assert "typeset" in result.stages_completed
    payload = json.loads((debug / "regions.json").read_text(encoding="utf-8"))
    assert payload["regions"][0]["translation"] == "Привет"
    assert payload["regions"][0]["speaker_gender"] == "male"


def test_rerender_uses_saved_translation(tmp_path):
    source = tmp_path / "page.png"
    Image.new("RGB", (180, 80), "white").save(source)
    region = TextRegion(
        id=1,
        bbox=(10, 10, 150, 50),
        text="Hello",
        translation="Привет",
        block_type="narration",
        class_name="text_free",
    )
    payload = {
        "source_path": str(source),
        "reading_direction": "ltr",
        "regions": [region.to_dict()],
    }
    regions_path = tmp_path / "regions.json"
    regions_path.write_text(json.dumps(payload), encoding="utf-8")
    pipeline = PagePipeline(Config(inpainter_backend="opencv"), translator=FakeTranslator())
    debug = tmp_path / "debug"
    result = pipeline.rerender(regions_path, debug_dir=debug)
    assert result.output_image.size == (180, 80)
    assert result.regions[0].translation == "Привет"
    assert (debug / "03_mask.png").exists()
    assert (debug / "04_clean.jpg").exists()
    assert (debug / "05_result.jpg").exists()
    assert {"load", "segment", "inpaint", "typeset"}.issubset(result.timings)
    assert all(result.timings[key] >= 0 for key in ("load", "segment", "inpaint", "typeset"))


def test_incremental_typeset_pipeline_matches_full_render(tmp_path):
    config = Config(inpainter_backend="opencv")
    config.layout_long_side = 0
    pipeline = PagePipeline(config)
    clean = Image.new("RGB", (320, 180), (244, 238, 230))
    previous = TextRegion(
        id=1, bbox=(35, 40, 100, 45), text="ONE", translation="ONE",
        block_type="narration",
    )
    previous_result, _ = pipeline.typeset_image(
        clean.copy(), [TextRegion.from_dict(previous.to_dict())], "en", warnings=[],
    )
    previous_bounds = dict(pipeline.typesetter._last_region_bounds)
    current = TextRegion.from_dict(previous.to_dict())
    current.translation = "TWO"
    incremental_result, _ = pipeline.typeset_image(
        clean.copy(), [TextRegion.from_dict(current.to_dict())], "en", warnings=[],
        incremental={
            "previous_regions": [TextRegion.from_dict(previous.to_dict())],
            "previous_result": previous_result,
            "previous_bounds": previous_bounds,
            "changed_region_ids": [1],
        },
    )
    assert pipeline._last_typeset_details["mode"] == "partial"
    full_result, _ = pipeline.typeset_image(
        clean.copy(), [TextRegion.from_dict(current.to_dict())], "en", warnings=[],
    )
    assert incremental_result.tobytes() == full_result.tobytes()
    config.layout_long_side = 1000
    scaled_result, _ = pipeline.typeset_image(
        clean.copy(), [TextRegion.from_dict(current.to_dict())], "en", warnings=[],
        incremental={
            "previous_regions": [TextRegion.from_dict(previous.to_dict())],
            "previous_result": previous_result,
            "previous_bounds": previous_bounds,
            "changed_region_ids": [1],
        },
    )
    assert pipeline._last_typeset_details["mode"] == "full"
    assert scaled_result.size == clean.size
    assert all(
        bounds is None or (bounds[2] <= clean.width and bounds[3] <= clean.height)
        for bounds in pipeline.typesetter._last_region_bounds.values()
    )
