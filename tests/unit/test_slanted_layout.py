"""Точность поворота, центра и переносов свободной наклонной надписи."""
import copy

import cv2
import numpy as np
import pytest
from PIL import Image, ImageFont

from src.components.adaptive_text import text_angle
from src.components.glyph_layout import glyph_mask
from src.components.slanted_layout import source_lines
from src.components.typesetter import COMIC_FONT, Typesetter
from src.models import TextRegion, TextStyle
from src.page_pipeline import _scale_regions


@pytest.mark.parametrize('angle', [-23.4, -11.7, 7.3, 18.6])
def test_subdegree_angle_and_source_center(angle):
    mask = glyph_mask('SAMPLE TEXT\nSECOND LINE', ImageFont.truetype(str(COMIC_FONT), 45))
    turned = mask.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    ink = np.asarray(turned)
    found, _ = text_angle(ink)
    assert abs(found-angle) <= 1., (found, angle)
    rows = source_lines(ink, (100, 80), (100, 80, turned.width, turned.height), found)
    assert len(rows) == 2
    region = TextRegion(1, (100, 80, turned.width, turned.height), translation='ПРИМЕР ТЕКСТА\nВТОРАЯ СТРОКА',
                        block_type='sfx', style=TextStyle(rotation=found, stroke_mode='none'),
                        auto_layout=dict(version=1, kind='free', source_bbox=[100, 80, turned.width, turned.height],
                                         ink_bbox=[100, 80, turned.width, turned.height], source_lines=rows))
    canvas = Image.new('RGB', (800, 500), 'white')
    setter = Typesetter()
    result, overflow = setter.render(canvas, [region])
    assert not overflow
    actual = np.asarray(result).min(axis=2) < 128
    measured = source_lines(actual.astype(np.uint8)*255, (0, 0), region.bbox, found)
    assert len(measured) == len(rows)
    for expected, observed in zip(rows, measured):
        assert abs(expected[0]+expected[2]/2-observed[0]-observed[2]/2) <= 2
        assert abs(expected[1]+expected[3]/2-observed[1]-observed[3]/2) <= 2
    assert abs(text_angle(actual.astype(np.uint8)*255)[0] - found) <= 1.
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    restored = TextRegion.from_dict(region.to_dict())
    again, _ = setter.render(canvas, [restored])
    assert np.array_equal(np.asarray(result), np.asarray(again))


def test_line_positions_survive_roundtrip_and_scaling():
    region = TextRegion(1, (10, 20, 200, 100), auto_layout=dict(version=1, kind='free',
        source_bbox=[10, 20, 200, 100], source_lines=[[15.5, 21.25, 180.5, 30.5], [45, 70, 90, 22]]))
    restored = TextRegion.from_dict(region.to_dict())
    assert restored.auto_layout == region.auto_layout
    _scale_regions([restored], 2.)
    assert restored.auto_layout['source_lines'][0] == [31, 42.5, 361, 61]
    _scale_regions([restored], .5)
    assert restored.auto_layout['source_lines'] == region.auto_layout['source_lines']


def test_caption_rows_use_text_pivot_despite_wrong_balloon_box():
    """Общая рамка двух карточек не сдвигает поворот и не обрезает буквы."""
    ink = glyph_mask('FIRST LINE\nSECOND LINE', ImageFont.truetype(str(COMIC_FONT), 40))
    turned = ink.rotate(12, Image.Resampling.BICUBIC, expand=True)
    bbox = (100, 80, turned.width, turned.height)
    rows = source_lines(np.asarray(turned), (100, 80), bbox, 12)
    region = TextRegion(1, bbox, bubble_bbox=(10, 10, 650, 400), block_type='dialogue',
                        translation='ПЕРВАЯ СТРОКА\nВТОРАЯ СТРОКА',
                        style=TextStyle(rotation=12, stroke_mode='none'),
                        auto_layout=dict(version=1, kind='free', mask_kind='bubble',
                                         source_bbox=list(bbox), ink_bbox=list(bbox), source_lines=rows))
    result, overflow = Typesetter().render(Image.new('RGB', (800, 500), 'white'), [region])
    assert not overflow
    observed = (np.asarray(result).min(axis=2) < 128).astype(np.uint8)*255
    actual = source_lines(observed, (0, 0), bbox, 12)
    assert len(actual) == 2
    for expected, found in zip(rows, actual):
        assert abs(expected[0]+expected[2]/2-found[0]-found[2]/2) <= 2
        assert abs(expected[1]+expected[3]/2-found[1]-found[3]/2) <= 2


def test_readable_caption_uses_line_gaps_for_larger_letters_and_roundtrips():
    """Читаемая реплика не наследует мелкий кегль самой тесной исходной строки."""
    from pathlib import Path
    from src.components.slanted_layout import line_raster
    font = Path('src/resources/fonts/Heroika-Regular.otf')
    geometry = dict(version=1, kind='free', source_bbox=[40, 40, 400, 180],
                    ink_bbox=[40, 40, 400, 180], source_lines=[[70, 70, 300, 30], [70, 140, 300, 30]])
    style = TextStyle(stroke_mode='none')
    text = 'Первая длинная реплика которую нужно удобно прочитать'
    _, old = line_raster(text, font, style, geometry)
    geometry.update(readable_caption=True, caption_padding=15)
    layer, fit = line_raster(text, font, style, geometry)
    assert fit['font_size'] >= old['font_size']*1.5
    assert fit['text'].replace('\n', ' ') == text
    repeated, _ = line_raster(text, font, style, geometry, frozen=fit)
    assert np.array_equal(np.asarray(layer), np.asarray(repeated))
    region = TextRegion(1, (40, 40, 400, 180), auto_layout=geometry)
    restored = TextRegion.from_dict(region.to_dict())
    _scale_regions([restored], 2)
    assert restored.auto_layout['caption_padding'] == 30
    _scale_regions([restored], .5)
    assert restored.auto_layout == geometry


@pytest.mark.parametrize('rows', [[], [[0, 0, -1, 5]], [[0, float('nan'), 5, 5]], [[0, 1, 3]], 'bad'])
def test_invalid_source_lines_are_ignored(rows):
    region = TextRegion(1, (10, 20, 200, 100))
    data = region.to_dict()
    data['auto_layout'] = dict(version=1, kind='free', source_lines=rows)
    assert TextRegion.from_dict(data).auto_layout is None


def test_separate_row_widths_are_preserved_without_stretching():
    from src.components.slanted_layout import line_raster
    style = TextStyle(stroke_mode='none')
    rows = [[20, 20, 220, 40], [80, 100, 100, 40]]
    geometry = dict(source_lines=rows, source_bbox=[20, 20, 220, 120], ink_bbox=[20, 20, 220, 120])
    layer, fit = line_raster('ДЛИННАЯ СТРОКА\nКОРОТКО', COMIC_FONT, style, geometry, 2)
    alpha = np.asarray(layer.getchannel('A'))
    first = np.where(alpha[:100] > 128)[1]
    second = np.where(alpha[100:] > 128)[1]
    assert first.max()-first.min() > second.max()-second.min()
    assert fit['text'] == 'ДЛИННАЯ СТРОКА\nКОРОТКО'


def test_noise_does_not_produce_rows():
    mask = np.zeros((60, 200), np.uint8)
    cv2.circle(mask, (30, 30), 1, 255, -1)
    assert source_lines(mask, (0, 0), (0, 0, 200, 60), 15) == []


def test_prepare_captures_rows_before_cleaning_and_respects_manual(monkeypatch):
    from src.components import adaptive_text
    alpha = glyph_mask('SAMPLE TEXT\nSECOND LINE', ImageFont.truetype(str(COMIC_FONT), 36))
    alpha = alpha.rotate(14.2, Image.Resampling.BICUBIC, expand=True)
    ink = np.asarray(alpha)
    region = TextRegion(1, (10, 20, alpha.width, alpha.height), text='SAMPLE TEXT SECOND LINE',
                        translation='ПРИМЕР ТЕКСТА ВТОРАЯ СТРОКА', block_type='narration')
    manual = copy.deepcopy(region)
    manual.id, manual.manual = 2, True
    monkeypatch.setattr(adaptive_text, 'source_ink', lambda image, r: (alpha, ink, (10, 20, 10+alpha.width, 20+alpha.height)))
    adaptive_text.prepare_regions(Image.new('RGB', (600, 400), 'white'), [region, manual])
    assert len(region.auto_layout['source_lines']) == 2
    assert abs(region.style.rotation - 14.2) <= 1
    assert manual.auto_layout is None


def test_outline_remains_in_external_roi():
    rows = [[-10, 20, 280, 45]]
    region = TextRegion(1, (10, 10, 240, 120), translation='ПРИМЕР НАКЛОННОЙ СТРОКИ', block_type='sfx',
                        style=TextStyle(rotation=17), auto_layout=dict(version=1, kind='free',
                        source_bbox=[10, 10, 240, 120], ink_bbox=[10, 10, 240, 120],
                        source_lines=rows, outline_px=3))
    _, overflow = Typesetter().render(Image.new('RGB', (400, 250), (50, 50, 50)), [region])
    assert not overflow


def test_thin_outlier_row_does_not_cap_common_kegl():
    """Ложно-тонкая полоса не душит кегль остальных свободных строк."""
    from src.components.slanted_layout import line_raster
    style = TextStyle(stroke_mode='none')
    fat = [[20, 20, 360, 90], [20, 130, 340, 12], [20, 160, 380, 100]]
    ink = [20, 20, 380, 240]
    geometry = dict(source_lines=fat, source_bbox=ink, ink_bbox=ink)
    _layer, fit = line_raster('ПРИНЦЕССА ПОМОГИТЕ ТОЖЕ', COMIC_FONT, style, geometry, 2)
    only_fat = dict(source_lines=[fat[0], fat[2]], source_bbox=ink, ink_bbox=ink)
    _same, expected = line_raster('ПРИНЦЕССА ПОМОГИТЕ ТОЖЕ', COMIC_FONT, style, only_fat, 2)
    thin_only = dict(source_lines=[fat[1]], source_bbox=ink, ink_bbox=ink)
    _tiny, tiny = line_raster('ТОЖЕ', COMIC_FONT, style, thin_only, 2)
    assert fit['font_size'] == expected['font_size']
    assert fit['font_size'] > tiny['font_size']


def test_frozen_source_rows_apply_enlarged_raster():
    """Увеличение кегля меняет реальные пиксели, а не только метаданные."""
    from src.components.slanted_layout import line_raster
    geometry = dict(source_lines=[[20, 20, 100, 12]], source_bbox=[20, 20, 100, 12],
                    ink_bbox=[20, 20, 100, 12])
    layer, fit = line_raster('ТЕКСТ', COMIC_FONT, TextStyle(stroke_mode='none'), geometry)
    enlarged = dict(fit, width=fit['width']*2, height=fit['height']*2, font_size=fit['font_size']*2)
    result, actual = line_raster('ТЕКСТ', COMIC_FONT, TextStyle(stroke_mode='none'), geometry, frozen=enlarged)
    assert result.size == (layer.width*2, layer.height*2)
    assert actual == enlarged
    assert np.count_nonzero(np.asarray(result.getchannel('A')) > 128) > 3 * np.count_nonzero(np.asarray(layer.getchannel('A')) > 128)
