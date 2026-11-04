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
