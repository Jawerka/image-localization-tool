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
