"""Дополнительный OCR: строгая геометрия и отсутствие дублей."""
from src.components.text_discovery import parse_discovery, refine_discovery
from src.models import TextRegion
from src.page_pipeline import PagePipeline
from src.config import Config
from PIL import Image
import pytest


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


def test_overlapping_fragment_of_existing_vertical_speech_is_not_new_text():
    """Ошибки чтения между словами не превращают край реплики в новый блок."""
    known = TextRegion(1, (500, 400, 130, 180), text='足りない物は私が朝までになんとかするから', block_type='dialogue')
    fragment = dict(text='い物はまでにかする', type='dialogue', x0=600, y0=500, x1=730, y1=630)
    assert parse_discovery({'blocks': [fragment]}, (1000, 1000), [known]) == []
    fragment.update(x0=750, x1=880)
    assert len(parse_discovery({'blocks': [fragment]}, (1000, 1000), [known])) == 1


def test_discovery_with_empty_detector_uses_shared_translation():
    class Detector:
        def detect(self, image):
            return []
    class Client:
        def chat_json(self, *args, **kwargs):
            if args[2] == 'read_missing_text':
                return {'text': 'BAM'}
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


def test_tall_page_tiles_map_verified_sound_to_full_image(monkeypatch):
    """Локальные координаты длинной страницы переводятся в общие один раз."""
    from src.components.text_discovery import discover_missing_text
    monkeypatch.setattr('src.components.text_discovery.refine_discovery', lambda image, regions, existing: regions)
    class Client:
        calls = 0
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': 'BAM'}
            if name == 'verify_missing_text':
                return {'blocks': [dict(text='BAM', type='sfx', x0=400, y0=400, x1=600, y1=600)]}
            self.calls += 1
            return {'blocks': [block()] if self.calls == 2 else []}
    client = Client()
    result = discover_missing_text(Image.new('RGB', (1000, 3600)), [], client)
    assert 2 <= client.calls <= 6
    assert len(result) == 1
    assert result[0].bbox[1] > 900


def test_unverified_sound_is_not_added_and_warning_is_explicit():
    """Слово модели с неверной рамкой не считается найденным звуком."""
    from src.components.text_discovery import discover_missing_text
    class Client:
        def chat_json(self, prompt, schema, name, **kwargs):
            return {'blocks': [block()] if name == 'missing_text' else []}
    warnings = []
    assert discover_missing_text(Image.new('RGB', (1000, 500)), [], Client(), warnings=warnings) == []
    assert warnings == ['VLM не подтвердил рамку дополнительного звука']


@pytest.mark.parametrize('reading', ['', 'SLIM', 'BAM EXTRA'])
def test_sfx_localization_requires_independent_reading_of_proposed_box(reading):
    """Подтверждение ожидаемого слова не разрешает очистку соседнего рисунка."""
    from src.components.text_discovery import _verify_sfx
    class Client:
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                assert 'BAM' not in prompt
                assert kwargs['images'][0].size == (50, 50)
                return {'text': reading}
            return {'blocks': [dict(text='BAM', type='sfx', x0=400, y0=400, x1=600, y1=600)]}
    region = TextRegion(1, (100, 100, 100, 100), text='BAM', block_type='sfx')
    assert not _verify_sfx(Image.new('RGB', (500, 500)), region, Client())
    assert region.bbox == (100, 100, 100, 100)


@pytest.mark.parametrize('reading, expected', [('', False), ('!', False), ('?!', True)])
def test_sfx_punctuation_is_not_equivalent_to_empty_crop(reading, expected):
    """Пустое чтение не подтверждает выразительную пунктуацию."""
    from src.components.text_discovery import _verify_sfx
    class Client:
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': reading}
            return {'blocks': [dict(text='?!', type='sfx', x0=400, y0=400, x1=600, y1=600)]}
    region = TextRegion(1, (100, 100, 100, 100), text='?!', block_type='sfx')
    assert _verify_sfx(Image.new('RGB', (500, 500)), region, Client()) is expected


def test_supplemental_narration_requires_reading_and_keeps_verified_location(monkeypatch):
    """Ошибка классификации звука не обходит контроль координат и не двигает проверенную рамку."""
    from src.components.text_discovery import discover_missing_text
    def move_elsewhere(image, regions, existing):
        for region in regions:
            region.bbox = (800, 800, 20, 20)
        return regions
    monkeypatch.setattr('src.components.text_discovery.refine_discovery', move_elsewhere)
    class Client:
        reading = ''
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': self.reading}
            return {'blocks': [dict(text='BLUSH', type='narration', x0=100, y0=100, x1=200, y1=200)]}
    client = Client()
    warnings = []
    assert discover_missing_text(Image.new('RGB', (1000, 1000)), [], client, warnings=warnings) == []
    assert warnings
    client.reading = 'BLUSH'
    result = discover_missing_text(Image.new('RGB', (1000, 1000)), [], client)
    assert len(result) == 1
    assert result[0].bbox != (800, 800, 20, 20)


def test_discovery_tiles_cover_large_square_and_are_bounded():
    """Лимит запросов не отбрасывает нижнюю часть большой квадратной страницы."""
    from src.components.text_discovery import _discovery_tiles
    tiles = _discovery_tiles((6000, 6000), 1800)
    assert len(tiles) <= 9
    for y in range(0, 6000, 100):
        for x in range(0, 6000, 100):
            assert any(a <= x < c and b <= y < d for a, b, c, d in tiles)


def test_failed_sfx_verification_preserves_previously_confirmed_blocks(monkeypatch):
    """Отказ одного кропа не удаляет уже подтверждённую надпись."""
    from src.components.text_discovery import discover_missing_text
    monkeypatch.setattr('src.components.text_discovery.refine_discovery', lambda image, regions, existing: regions)
    class Client:
        verification = 0
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': 'BAM'}
            if name == 'missing_text':
                second = block('BOOM')
                second.update(x0=600, x1=700)
                return {'blocks': [block(), second]}
            self.verification += 1
            if self.verification == 2:
                raise RuntimeError('offline')
            return {'blocks': [dict(text='BAM', type='sfx', x0=400, y0=400, x1=600, y1=600)]}
    warnings = []
    result = discover_missing_text(Image.new('RGB', (1000, 500)), [], Client(), warnings=warnings)
    assert [r.text for r in result] == ['BAM']
    assert any('RuntimeError' in item for item in warnings)


def test_failed_tile_preserves_other_tiles_and_reports_incomplete_search(monkeypatch):
    """Ошибка следующего фрагмента не отменяет результат первого."""
    from src.components.text_discovery import discover_missing_text
    monkeypatch.setattr('src.components.text_discovery.refine_discovery', lambda image, regions, existing: regions)
    class Client:
        tile = 0
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': 'WORDS'}
            if name == 'verify_missing_text':
                return {'blocks': [dict(text='WORDS', type='narration', x0=400, y0=400, x1=600, y1=600)]}
            self.tile += 1
            if self.tile != 1:
                raise RuntimeError('offline')
            item = block('WORDS')
            item['type'] = 'narration'
            return {'blocks': [item]}
    warnings = []
    result = discover_missing_text(Image.new('RGB', (1000, 3600)), [], Client(), warnings=warnings)
    assert [r.text for r in result] == ['WORDS']
    assert warnings and all('RuntimeError' in item for item in warnings)


@pytest.mark.parametrize('size', [(1200, 3595), (3595, 1200), (6000, 6000),
                                 (300, 16000), (16000, 300), (1280, 1707)])
def test_discovery_tiles_have_twenty_percent_overlap_and_full_coverage(size):
    """Граница тайла не разрезает слово из-за исчезнувшего перекрытия."""
    from src.components.text_discovery import _discovery_tiles
    tiles = _discovery_tiles(size, 1800)
    assert 1 <= len(tiles) <= 9
    for axis, length in enumerate(size):
        intervals = sorted(set((tile[axis], tile[axis+2]) for tile in tiles))
        assert intervals[0][0] == 0
        assert intervals[-1][1] == length
        for (start, end), (next_start, next_end) in zip(intervals, intervals[1:]):
            overlap = end-next_start
            assert overlap * 5 >= min(end-start, next_end-next_start)


def test_sfx_budget_is_shared_between_tiles_and_does_not_starve_later_text(monkeypatch):
    """Плохие предложения первого фрагмента не отнимают бюджет у следующих."""
    from src.components.text_discovery import discover_missing_text, _discovery_tiles
    monkeypatch.setattr('src.components.text_discovery.refine_discovery', lambda image, regions, existing: regions)
    class Client:
        tiles = 0
        verifications = 0
        def chat_json(self, prompt, schema, name, **kwargs):
            if name == 'read_missing_text':
                return {'text': 'REAL'}
            if name == 'missing_text':
                self.tiles += 1
                if self.tiles == 1:
                    return {'blocks': [dict(text='FAKE', type='sfx', x0=(i%6)*150,
                                            y0=(i//6)*200, x1=(i%6)*150+80,
                                            y1=(i//6)*200+80) for i in range(24)]}
                if self.tiles == 2:
                    return {'blocks': [block('REAL')]}
                return {'blocks': []}
            self.verifications += 1
            return {'blocks': [] if self.tiles == 1 else [dict(text='REAL', type='sfx', x0=400,
                                                              y0=400, x1=600, y1=600)]}
    client = Client()
    warnings = []
    result = discover_missing_text(Image.new('RGB', (1000, 3600)), [], client, warnings=warnings)
    assert [r.text for r in result] == ['REAL']
    assert client.tiles == len(_discovery_tiles((1000, 3600), 1800))
    assert client.verifications <= 24
    assert any('бюджет' in item for item in warnings)
