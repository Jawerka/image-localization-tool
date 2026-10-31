"""Дополнительный OCR: строгая геометрия и отсутствие дублей."""
from src.components.text_discovery import parse_discovery
from src.models import TextRegion
from src.page_pipeline import PagePipeline
from src.config import Config
from PIL import Image


def block(text='BAM', **changes):
    return dict(text=text, type='sfx', x0=100, y0=100, x1=200, y1=200, **changes)


def test_explicit_xyxy_duplicates_and_separate_repetitions():
    known = TextRegion(4, (100, 50, 100, 50), text='BAM', block_type='sfx')
    repeated = block()
    repeated.update(x0=600, x1=700)
    extras = parse_discovery({'blocks': [block(), repeated, repeated]}, (1000, 500), [known])
    assert len(extras) == 1
    assert extras[0].bbox == (600, 50, 100, 50)
    assert extras[0].id == 5
    assert extras[0].translation == ''


def test_rejects_invalid_or_noncontent_boxes():
    cases = []
    for key, value in [('x0', -1), ('x1', 100), ('x1', float('nan')), ('y1', 1001),
                       ('text', ''), ('type', 'sign'), ('x0', '100')]:
        item = block()
        item[key] = value
        cases.append(item)
    assert parse_discovery({'blocks': cases}, (1000, 500), []) == []


def test_discovery_with_empty_detector_uses_shared_translation():
    class Detector:
        def detect(self, image):
            return []
    class Client:
        def chat_json(self, *args, **kwargs):
            return {'blocks': [block()]}
    class Translator:
        def translate(self, image, regions, *args, **kwargs):
            assert [r.text for r in regions] == ['BAM']
            regions[0].translation = 'БАМ'
            return regions
    pipeline = PagePipeline(Config(layout_long_side=0, sfx_mode='replace'), detector=Detector(), ocr=object(), translator=Translator())
    pipeline.ocr_name = 'vlm'
    pipeline._shared_client = Client()
    result = pipeline.analyze(Image.new('RGB', (1000, 500), 'white'), '', 'en', 'ru')
    assert len(result.regions) == 1
    assert result.regions[0].translation == 'БАМ'


def test_failed_discovery_preserves_existing_ocr():
    from tests.integration.test_page_pipeline import FakeDetector, FakeOcr, FakeTranslator
    class Client:
        def chat_json(self, *args, **kwargs):
            raise RuntimeError('offline')
    pipeline = PagePipeline(Config(layout_long_side=0), detector=FakeDetector(), ocr=FakeOcr(), translator=FakeTranslator())
    pipeline.ocr_name = 'vlm'
    pipeline._shared_client = Client()
    result = pipeline.analyze(Image.new('RGB', (200, 120), 'white'), '', 'en', 'ru')
    assert result.regions[0].translation
    assert any('offline' in warning for warning in result.warnings)
