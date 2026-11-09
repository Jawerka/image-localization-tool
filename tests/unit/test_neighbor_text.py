"""Нераспознанное соседнее слово не стирается вместе с основной репликой."""
import numpy as np
import pytest
from PIL import Image

from src.components.neighbor_text import protect_neighbor_text
from src.components.rapid_ocr import OcrWord
from src.models import TextRegion


def caption(text='A LONG CAPTION'):
    return TextRegion(1, (20, 20, 150, 130), text=text, translation='Перевод', block_type='narration',
                      auto_layout={'version': 1, 'kind': 'bubble', 'outline_px': 3,
                                   'contour': [[20, 20], [170, 20], [170, 150], [20, 150]]})


def word(text='Shake', confidence=.999):
    return OcrWord(text, (70, 80, 70, 40), confidence,
                   ((70, 95), (130, 80), (140, 105), (80, 120)))


def test_preserves_unclaimed_neighbor_and_reports_incomplete_recognition():
    mask = np.full((200, 200), 255, np.uint8)
    warnings = []
    result = protect_neighbor_text(Image.new('RGB', (200, 200)), [caption()], mask,
                                   warnings=warnings, words=[word()])
    assert result[100, 100] == 0 and result[30, 30] == 255
    assert mask[100, 100] == 255
    assert len(warnings) == 1 and 'нераспознан' in warnings[0]


@pytest.mark.parametrize('source, reading', [('HELP!', 'HELPI'), ('SIGH', 'SIGHY'),
                                           ('GGG', 'TUGGG'), ('TUG', 'TUGGG'), ('SHAKE', 'Shake')])
def test_local_ocr_difference_does_not_preserve_target_letters(source, reading):
    mask = np.full((200, 200), 255, np.uint8)
    result = protect_neighbor_text(Image.new('RGB', (200, 200)), [caption(source)], mask,
                                   words=[word(reading)])
    assert np.array_equal(result, mask)


def test_manual_region_and_weak_reading_are_not_automatic_protection():
    mask = np.full((200, 200), 255, np.uint8)
    manual = caption()
    manual.manual = True
    for regions, words in [([manual], [word()]), ([caption(), manual], [word()]),
                           ([caption()], [word(confidence=.7)])]:
        result = protect_neighbor_text(Image.new('RGB', (200, 200)), regions, mask, words=words)
        assert np.array_equal(result, mask)


def test_failed_optional_local_reading_preserves_mask_and_reports_warning(monkeypatch):
    def fail():
        raise RuntimeError('offline')
    monkeypatch.setattr('src.components.neighbor_text._discovery_ocr', fail)
    mask = np.full((200, 200), 255, np.uint8)
    warnings = []
    result = protect_neighbor_text(Image.new('RGB', (200, 200)), [caption()], mask, warnings=warnings)
    assert np.array_equal(result, mask)
    assert any('RuntimeError' in warning for warning in warnings)


def test_protected_geometry_roundtrips_and_scales_with_page():
    from src.page_pipeline import _working_regions, _commit_regions
    region = caption()
    protect_neighbor_text(Image.new('RGB', (200, 200)), [region],
                          np.full((200, 200), 255, np.uint8), words=[word()])
    points = region.auto_layout['protected_text'][0]
    restored = TextRegion.from_dict(region.to_dict())
    scaled = _working_regions([restored], 2)
    assert np.allclose(scaled[0].auto_layout['protected_text'][0], np.asarray(points) * 2)
    _commit_regions([restored], scaled, 2)
    assert np.allclose(restored.auto_layout['protected_text'][0], points)


def test_typesetter_cannot_overpaint_protected_source_even_in_fallback():
    from src.components.neighbor_text import protected_text_mask
    from src.components.typesetter import Typesetter
    region = caption()
    region.translation = 'ДЛИННЫЙ РУССКИЙ ПЕРЕВОД ' * 30
    rgb = np.full((200, 200, 3), 255, np.uint8)
    rgb[95:110, 85:120] = (0, 20, 80)
    image = Image.fromarray(rgb)
    protect_neighbor_text(image, [region], np.full((200, 200), 255, np.uint8), words=[word()])
    blocked = protected_text_mask(rgb.shape, region) > 0
    rendered, overflow = Typesetter(min_font_size=12, max_font_size=24).render(image, [region], force=True)
    assert np.array_equal(np.asarray(rendered)[blocked], rgb[blocked])
    assert region.id in overflow
