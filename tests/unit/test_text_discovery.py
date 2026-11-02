"""Дополнительный OCR: строгая геометрия и отсутствие дублей."""
from src.components.text_discovery import parse_discovery, refine_discovery
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


def test_supplemental_box_on_balloon_edge_moves_to_enclosed_letters():
    """Короткая реплика смещена VLM на обводку справа от букв."""
    import cv2
    import numpy as np
    rgb = np.full((260, 400, 3), 255, np.uint8)
    cv2.ellipse(rgb, (175, 130), (130, 90), 0, 0, 360, (0, 0, 0), 4)
    cv2.putText(rgb, 'HI.', (110, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    region = TextRegion(1, (250, 95, 60, 100), text='HI.', block_type='narration')
    refine_discovery(Image.fromarray(rgb), [region])
    x, y, w, h = region.bbox
    assert 105 <= x <= 120 and 100 <= y <= 115
    assert x + w < 220 and y + h <= 155
    assert region.bubble_bbox is not None
    assert region.block_type == 'dialogue'


def test_supplemental_refinement_requires_closed_balloon_and_no_existing_text():
    """Белый фон без баллона и уже известные надписи не перехватываются."""
    import cv2
    import numpy as np
    rgb = np.full((260, 400, 3), 255, np.uint8)
    cv2.putText(rgb, 'HI.', (110, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    region = TextRegion(1, (250, 95, 60, 100), text='HI.', block_type='narration')
    original = region.bbox
    refine_discovery(Image.fromarray(rgb), [region])
    assert region.bbox == original and region.bubble_bbox is None
    cv2.ellipse(rgb, (175, 130), (130, 90), 0, 0, 360, (0, 0, 0), 4)
    known = TextRegion(2, (100, 100, 120, 60), text='HI.')
    refine_discovery(Image.fromarray(rgb), [region], [known])
    assert region.bbox == original and region.bubble_bbox is None


def test_supplemental_sfx_refines_only_unique_exact_local_source_match(monkeypatch):
    """Нормализация допускает обводочную пунктуацию, но не похожее другое слово."""
    from src.components.rapid_ocr import OcrWord
    class Ocr:
        def _words(self, crop):
            assert crop.size == (300, 260)
            return [OcrWord('SLAM!', (90, 25, 110, 50), .98),
                    OcrWord('SLIM', (80, 110, 100, 50), .99)]
    monkeypatch.setattr('src.components.text_discovery._discovery_ocr', lambda: Ocr())
    region = TextRegion(1, (120, 200, 100, 60), text='Slam', block_type='sfx',
                        auto_layout={'kind': 'free'})
    refine_discovery(Image.new('RGB', (500, 500), 'white'), [region])
    assert region.bbox == (110, 125, 110, 50)
    assert region.auto_layout is None


def test_supplemental_sfx_keeps_ambiguous_low_confidence_and_known_words(monkeypatch):
    """Повтор слова, известный регион или слабое чтение не двигают рамку."""
    from src.components.rapid_ocr import OcrWord
    class Ocr:
        words = []
        def _words(self, crop):
            return self.words
    ocr = Ocr()
    monkeypatch.setattr('src.components.text_discovery._discovery_ocr', lambda: ocr)
    match = OcrWord('SLAM', (90, 25, 110, 50), .98)
    for words, known in [([match, OcrWord('SLAM', (90, 185, 110, 50), .98)], []),
                         ([OcrWord('SLAM', match.bbox, .6)], []),
                         ([OcrWord('SLIM', match.bbox, .99)], []),
                         ([match], [TextRegion(2, (110, 125, 110, 50), text='SLAM')])]:
        region = TextRegion(1, (120, 200, 100, 60), text='SLAM', block_type='sfx')
        ocr.words = words
        refine_discovery(Image.new('RGB', (500, 500), 'white'), [region], known)
        assert region.bbox == (120, 200, 100, 60)


def test_supplemental_sfx_combines_two_nearby_exact_word_parts(monkeypatch):
    """Разные строки BA- и DUMP образуют одну подтверждённую надпись."""
    from src.components.rapid_ocr import OcrWord
    class Ocr:
        def _words(self, crop):
            return [OcrWord('BA-', (100, 90, 90, 55), .99),
                    OcrWord('DUMP', (80, 125, 120, 60), .99)]
    monkeypatch.setattr('src.components.text_discovery._discovery_ocr', lambda: Ocr())
    region = TextRegion(1, (120, 200, 100, 60), text='BA-DUMP', block_type='sfx')
    refine_discovery(Image.new('RGB', (500, 500), 'white'), [region])
    assert region.bbox == (100, 190, 120, 95)


def test_supplemental_repeated_sfx_selects_distinctly_nearest_match(monkeypatch):
    """Повтор в другом месте не мешает локализовать явно ближайший звук."""
    from src.components.rapid_ocr import OcrWord
    class Ocr:
        def _words(self, crop):
            return [OcrWord('HAH', (100, 110, 100, 50), .99),
                    OcrWord('HAH', (90, 10, 100, 50), .99)]
    monkeypatch.setattr('src.components.text_discovery._discovery_ocr', lambda: Ocr())
    region = TextRegion(1, (120, 200, 100, 60), text='HAH...', block_type='sfx')
    refine_discovery(Image.new('RGB', (500, 500), 'white'), [region])
    assert region.bbox == (120, 210, 100, 50)


def test_supplemental_sfx_missing_local_ocr_preserves_frame(monkeypatch):
    """Отсутствующие компоненты не запускают загрузку и не меняют геометрию."""
    def missing():
        raise RuntimeError('offline models unavailable')
    monkeypatch.setattr('src.components.text_discovery._discovery_ocr', missing)
    region = TextRegion(1, (120, 200, 100, 60), text='SLAM', block_type='sfx')
    refine_discovery(Image.new('RGB', (500, 500), 'white'), [region])
    assert region.bbox == (120, 200, 100, 60)
