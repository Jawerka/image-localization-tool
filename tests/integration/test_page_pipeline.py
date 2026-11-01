"""PagePipeline на моках OCR и перевода, без LLM и без детектора."""

import json

from PIL import Image, ImageDraw

from src.config import Config
from src.components.bubble_detector import Detection
from src.models import TextRegion, MaskStroke
from src.page_pipeline import PagePipeline


def test_cleanup_reconstructs_transparent_panel_and_keeps_manual_exclusion():
    import cv2
    import numpy as np

    class RecordingInpainter:
        def __init__(self):
            self.calls = []
            self.last_warnings = []

        def inpaint(self, image, mask, allow_flat_fill=True):
            self.calls.append(allow_flat_fill)
            return image.copy()

    rgb = np.full((120, 240, 3), 255, np.uint8)
    rgb[:] = np.linspace(205, 255, 240, dtype=np.uint8)[None, :, None]
    cv2.putText(rgb, 'HELLO', (35, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    region = TextRegion(1, (25, 40, 150, 45), text='HELLO', translation='ПРИВЕТ', bubble_bbox=(10, 10, 210, 100))
    painter = RecordingInpainter()
    pipeline = PagePipeline(Config(layout_long_side=0), inpainter=painter)
    mask, _ = pipeline.clean(Image.fromarray(rgb), [region], strokes=[MaskStroke(mode='erase', points=[(55, 65)], radius=6)])
    assert painter.calls and False in painter.calls
    assert mask[65, 55] == 0


def test_skipped_light_text_never_reaches_inpainter():
    import cv2
    import numpy as np

    rgb = np.full((120, 240, 3), 35, np.uint8)
    cv2.putText(rgb, 'HELLO', (35, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    region = TextRegion(1, (25, 40, 150, 45), text='HELLO', translation='ПРИВЕТ', skip=True)
    class NoInpainter:
        def inpaint(self, *args, **kwargs):
            raise AssertionError('Пропущенный регион не должен очищаться')

    mask, cleaned = PagePipeline(Config(layout_long_side=0), inpainter=NoInpainter()).clean(Image.fromarray(rgb), [region])
    assert not np.any(mask)
    assert np.array_equal(np.asarray(cleaned), rgb)


def test_current_ocr_roles_reach_retouch_without_experimental_flags():
    """Настоящая классификация OCR ведёт светлый текст и звук в общую очистку."""
    import cv2
    import numpy as np
    from src.components.rapid_ocr import OcrWord, RapidOcr

    rgb = np.full((120, 500, 3), 35, np.uint8)
    cv2.putText(rgb, 'HELLO', (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.putText(rgb, 'BANG', (280, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 7)
    cv2.putText(rgb, 'BANG', (280, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)

    class Detector:
        def detect(self, image):
            return [Detection((10, 35, 170, 50), 2, 'text_free', .99),
                    Detection((270, 35, 110, 50), 2, 'text_free', .99)]

    class RecordingInpainter:
        last_warnings = []

        def __init__(self):
            self.calls = []

        def inpaint(self, image, mask, allow_flat_fill=True):
            self.calls.append(allow_flat_fill)
            return image.copy()

    ocr = RapidOcr()
    ocr._words = lambda image: [OcrWord('YOUR LUNCH SWEETHEART.', (20, 45, 130, 30), .99),
                               OcrWord('BANG', (280, 45, 90, 30), .99)]
    painter = RecordingInpainter()
    pipeline = PagePipeline(Config(layout_long_side=0), detector=Detector(), ocr=ocr,
                            translator=FakeTranslator(), inpainter=painter)
    image = Image.fromarray(rgb)
    analyzed = pipeline.analyze(image, 'synthetic.png', 'en', 'ru')
    assert [r.block_type for r in analyzed.regions] == ['narration', 'sfx']
    mask, cleaned = pipeline.clean(image, analyzed.regions)
    white = np.min(rgb, axis=2) > 210
    assert np.mean(mask[white] > 0) > .98
    assert np.any(mask[:, :200]) and np.any(mask[:, 250:])
    assert not np.any(mask[:, 200:250])
    assert painter.calls and False in painter.calls
    assert cleaned.size == image.size
    assert 'typeset' not in analyzed.stages_completed


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


def test_sfx_default_reaches_shared_translation_and_drawable_filter():
    from src.app.settings import AppSettings
    from src.app.jobs import _snapshot
    from src.app.remote import _pipeline_fingerprint

    class SoundTranslator:
        def translate(self, image, regions, source_lang, target_lang, glossary=None, translate_sfx=False):
            assert translate_sfx is self.expected
            for region in regions:
                region.translation = 'БАХ' if translate_sfx else ''
            return regions

    for settings, enabled in [(AppSettings(), True), (AppSettings(sfx_mode='skip'), False)]:
        snapshot = _snapshot(settings)
        translator = SoundTranslator()
        translator.expected = enabled
        pipeline = PagePipeline(AppSettings.from_dict(snapshot).to_config(), translator=translator)
        sound = TextRegion(1, (10,10,80,30), text='BANG', block_type='sfx')
        result = pipeline._translate(Image.new('RGB',(100,60)), [sound], 'en', 'ru', [])
        assert bool(pipeline._drawable(result)) is enabled
        sound.translation = ''
        assert not pipeline._drawable([sound])
    assert _pipeline_fingerprint(AppSettings()) != _pipeline_fingerprint(AppSettings(sfx_mode='skip'))
