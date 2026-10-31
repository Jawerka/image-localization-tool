"""Контракты переноса геометрии, маски и безопасных глифов."""
import copy
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from src.components.adaptive_text import fit_balloon_shape, text_angle, prepare_regions, adaptive_masks
from src.components.glyph_layout import glyph_plan, glyph_mask
from src.components.typesetter import Typesetter
from src.models import TextRegion, TextStyle
from src.page_pipeline import _scale_regions

FONT = Path('src/resources/fonts/Heroika-Regular.otf')


def test_source_ink_keeps_outline_joined_across_lines():
    """Соединённый ореол нескольких строк нельзя удалить как высокое пятно."""
    from src.components.adaptive_text import source_ink

    rgb = np.full((170, 260, 3), 205, np.uint8)
    expected = np.zeros(rgb.shape[:2], np.uint8)
    cv2.line(rgb, (23, 25), (23, 140), (255, 255, 255), 5)
    for y in (50, 95, 140):
        cv2.putText(rgb, 'WORDS', (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 8)
        cv2.putText(rgb, 'WORDS', (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (10, 10, 10), 2)
        cv2.putText(expected, 'WORDS', (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
    region = TextRegion(1, (10, 10, 230, 145), text='WORDS WORDS WORDS', block_type='narration')
    _, ink, (a, b, c, d) = source_ink(Image.fromarray(rgb), region)
    assert np.mean(ink[expected[b:d, a:c] > 0] > 0) >= .99


@pytest.mark.parametrize('angle', [-33, -9, 0, 9, 33])
def test_direction_follows_lines(angle):
    layer = Image.new('L', (500, 220))
    paint = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT), 30)
    for y in (25, 85, 145):
        paint.text((30, y), 'Several words in a line', font=font, fill=255)
    ink = np.array(layer.rotate(angle, expand=True))
    result, _ = text_angle(ink)
    assert abs(result - angle) <= 2


def test_balloon_fit_prefers_the_larger_size_when_middle_sizes_fail(monkeypatch):
    def fake_layout(text, font, draw, spans, hyphen, align, letter_spacing=0, line_spacing=0, stroke_pad=0):
        assert stroke_pad == 2
        return [("", 80, 80)], font.size in (50, 30)

    monkeypatch.setattr("src.components.bubble_layout.layout_in_shape", fake_layout)
    area = np.full((200, 200), 255, dtype=np.uint8)
    region = TextRegion(1, (0, 0, 200, 200), translation="A")
    _placed, font, fits = fit_balloon_shape(
        area, region, "A", FONT, "ru", min_size=7, max_size=60, stroke_pad=lambda _size: 2,
    )
    assert fits is True
    assert font.size == 50


def test_metadata_roundtrip_and_scaling():
    region = TextRegion(1, (10, 20, 50, 30), auto_layout={
        'version': 1, 'kind': 'bubble', 'ink_bbox': [10, 20, 50, 30],
        'contour': [[10, 20], [60, 20], [60, 50]], 'outline_px': 3,
    })
    copied = TextRegion.from_dict(region.to_dict())
    _scale_regions([copied], 2)
    assert copied.auto_layout['ink_bbox'] == [20, 40, 100, 60]
    assert copied.auto_layout['outline_px'] == 6
    _scale_regions([copied], .5)
    assert copied.auto_layout == region.auto_layout


def test_short_vertical_and_manual_geometry_stay_untouched():
    image = Image.new('RGB', (160, 170), 'white')
    ImageDraw.Draw(image).text((25, 40), 'TEXT', font=ImageFont.truetype(str(FONT), 30), fill='black')
    region = TextRegion(1, (20, 20, 100, 120), text='あいう', class_name='text_bubble')
    manual = copy.deepcopy(region)
    manual.id = 2
    manual.edited = True
    manual.style = TextStyle(rotation=17, font_id='manual', stroke_mode='none')
    before = manual.to_dict()
    prepare_regions(image, [region, manual])
    assert region.style.rotation == 0
    assert manual.to_dict() == before


def test_cleanup_has_full_margin_and_protects_neighbour():
    image = Image.new('RGB', (160, 100), 'white')
    paint = ImageDraw.Draw(image)
    paint.rectangle((40, 30, 44, 65), fill='black')
    sound = TextRegion(1, (38, 28, 9, 40), block_type='sfx', text='BAM', translation='БАМ')
    speech = TextRegion(2, (53, 28, 40, 40), text='Hello', translation='Привет', bubble_bbox=(50, 20, 50, 60))
    prepare_regions(image, [sound, speech])
    other = np.zeros((100, 160), np.uint8)
    free = other.copy()
    _, free = adaptive_masks(image, [sound, speech], other, free)
    assert free[45, 32] > 0
    assert not np.any(free[28:68, 53:93])


def test_italic_pair_uses_actual_separate_ink():
    path = Path('C:/Windows/Fonts/comicz.ttf')
    if not path.is_file():
        pytest.skip('Реальный Windows-шрифт отсутствует')
    font = ImageFont.truetype(str(path), 144)
    plan = glyph_plan('та', font, 3)
    assert plan[1][1] > font.getlength('т')
    masks = []
    for char, x in plan:
        im = Image.new('L', (400, 250))
        ImageDraw.Draw(im).text((x + 20, 10), char, font=font, fill=255, stroke_width=3)
        masks.append(np.asarray(im) > 127)
    assert not np.any(masks[0] & masks[1])
    assert glyph_mask('та', font, 3).getbbox() is not None


def test_rotated_bubble_full_preview_and_snapshot_agree():
    image = Image.new('RGB', (500, 330), 'white')
    region = TextRegion(1, (110, 90, 210, 120), text='A few words', translation='Несколько слов в облачке',
                        bubble_bbox=(50, 40, 380, 220), style=TextStyle(rotation=9, stroke_mode='none'))
    setter = Typesetter(min_font_size=7, max_font_size=60, margin_ratio=.04)
    result, overflow = setter.render(image, [region])
    assert not overflow
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    repeated, overflow = setter.render(image, [region])
    assert not overflow
    assert np.array_equal(np.asarray(result), np.asarray(repeated))
    layer, origin, overflow = setter.render_layer(image, [region])
    canvas = image.convert('RGBA')
    canvas.alpha_composite(layer, origin)
    assert np.array_equal(np.asarray(result), np.asarray(canvas.convert('RGB')))


def test_cleanup_does_not_overwrite_manual_style():
    from src.components.text_segmenter import segment_regions
    image = Image.new('RGB', (150, 90), 'white')
    ImageDraw.Draw(image).text((20, 25), 'HELLO', font=ImageFont.truetype(str(FONT), 20), fill='black')
    region = TextRegion(1, (18, 20, 110, 40), text='HELLO', edited=True,
                        style=TextStyle(fill_rgb=(25, 50, 70), rotation=17, uppercase=False, font_size=28, stroke_mode='none'))
    before = region.style.to_dict()
    assert np.any(segment_regions(image, [region]))
    assert region.style.to_dict() == before


def test_adaptive_free_snapshot_preview_and_manual_rotation():
    from src.components.font_catalog import assign_stylized_fonts
    from src.components.typesetter import _frozen_layout
    image = Image.new('RGB', (500, 300), 'white')
    region = TextRegion(1, (60, 50, 220, 100), text='You are mean!', translation='Ты такая\nзлюка!', block_type='narration')
    region.auto_layout = dict(version=1, kind='free', ink_bbox=[60, 50, 220, 100], outline_px=3)
    assign_stylized_fonts([region])
    region.style.rotation = 9
    setter = Typesetter()
    rendered, overflow = setter.render(image, [region])
    assert not overflow
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    assert region.style.font_size < 144
    repeated, _ = setter.render(image, [region])
    assert np.array_equal(np.asarray(rendered), np.asarray(repeated))
    layer, origin, _ = setter.render_layer(image, [region])
    canvas = image.convert('RGBA')
    canvas.alpha_composite(layer, origin)
    assert np.array_equal(np.asarray(rendered), np.asarray(canvas.convert('RGB')))
    region.style.rotation = 15
    assert _frozen_layout(region) is not None
    assert _frozen_layout(region)['raster_fit'] == region.layout_snapshot['raster_fit']


def test_adaptive_bubble_reports_no_hidden_clipped_ink():
    from src.components.typesetter import interior_mask
    image = Image.new('RGB', (500, 300), 'white')
    region = TextRegion(1, (80, 70, 280, 100), text='Several words', translation='Несколько слов внутри облачка',
                        bubble_bbox=(50, 30, 400, 230), auto_layout={'version': 1, 'kind': 'bubble'},
                        style=TextStyle(rotation=33, font_id='Heroika-Regular'))
    setter = Typesetter()
    layer, origin, overflow = setter.render_layer(image, [region], capture=True, trim=False)
    canvas = Image.new('RGBA', image.size)
    canvas.alpha_composite(layer, origin)
    area = interior_mask(np.asarray(image), region)
    assert not overflow
    assert not np.any((np.asarray(canvas)[..., 3] > 20) & (area == 0))


def test_asymmetric_free_ink_stays_centered_after_rotation():
    from src.components.typesetter import interior_mask
    image = Image.new('RGB', (600, 300), 'white')
    region = TextRegion(1, (80, 90, 299, 129), block_type='sfx', text='CLACK!', translation='Щёлк!',
                        auto_layout=dict(version=1, kind='free', source_bbox=[80, 90, 299, 129],
                                         ink_bbox=[87, 87, 278, 135], outline_px=3),
                        style=TextStyle(rotation=-12, font_id='impact'))
    from src.components.font_catalog import resolve_font_path
    if resolve_font_path('impact') is None:
        region.style.font_id = 'Heroika-Regular'
    setter = Typesetter()
    layer, origin, over = setter.render_layer(image, [region], capture=True, trim=False)
    canvas = Image.new('RGBA', image.size)
    canvas.alpha_composite(layer, origin)
    area = interior_mask(np.asarray(image), region)
    assert not over
    assert not np.any((np.asarray(canvas)[..., 3] > 20) & (area == 0))


def test_small_document_label_gets_complete_text():
    region = TextRegion(1, (10, 10, 53, 18), text='Follow', translation='Подписаться',
                        document=True, block_type='narration', style=TextStyle(alignment='left'))
    _, overflow = Typesetter(min_font_size=10, max_font_size=128).render(Image.new('RGB', (100, 40), 'white'), [region])
    assert not overflow
    assert 6 <= region.style.font_size < 10


@pytest.mark.parametrize('bad', [{'version': 1, 'kind': 'free', 'ink_bbox': [0, 0, None, 10]},
                                {'version': 1, 'kind': 'free', 'outline_px': float('nan')},
                                {'version': 1, 'kind': 'bubble', 'contour': [[1], [2], [3]]}])
def test_bad_optional_metadata_falls_back(bad):
    region = TextRegion(1, (0, 0, 50, 50))
    raw = region.to_dict()
    raw['auto_layout'] = bad
    assert TextRegion.from_dict(raw).auto_layout is None


def test_adaptive_font_has_bundled_fallback_and_respects_manual_choice():
    from src.components.font_catalog import assign_stylized_fonts, FontFace
    face = FontFace('Liber-Struct', 'Liber', 'fallback.ttf', 'sfx', True)
    region = TextRegion(1, (0, 0, 50, 50), text='BAM', translation='БАМ', block_type='sfx',
                        auto_layout={'version': 1, 'kind': 'free'})
    assign_stylized_fonts([region], faces=[face])
    assert region.style.font_id == 'Liber-Struct'
    region.style.font_id = 'chosen-by-user'
    assign_stylized_fonts([region], faces=[face])
    assert region.style.font_id == 'chosen-by-user'


def test_native_outline_survives_working_upscale():
    from src.config import Config
    from src.page_pipeline import PagePipeline
    image = Image.new('RGB', (400, 250), (128, 128, 128))
    original = TextRegion(1, (100, 60, 80, 120), text='THUD', translation='I', block_type='sfx',
                          style=TextStyle(fill_rgb=(18, 18, 18), font_id='Heroika-Regular'),
                          auto_layout=dict(version=1, kind='free', source_bbox=[100, 60, 80, 120],
                                           ink_bbox=[100, 60, 80, 120], outline_px=3, mask_pad_px=8))
    widths = []
    for side in (0, 2000):
        pipeline = PagePipeline(Config(layout_long_side=side))
        rendered, over = pipeline.typeset_image(image, [copy.deepcopy(original)], 'en')
        assert not over
        row = np.asarray(rendered)[120, :, 0]
        black = np.flatnonzero(row < 60)
        white = np.flatnonzero(row > 220)
        widths.append((black[0] - white[0], white[-1] - black[-1]))
    assert all(2 <= value <= 4 for pair in widths for value in pair)


def test_linked_balloon_geometry_comes_from_original_pixels():
    from src.components.typesetter import interior_mask
    image = Image.new('RGB', (400, 240), (120, 120, 120))
    paint = ImageDraw.Draw(image)
    paint.ellipse((30, 20, 365, 220), fill='white', outline='black', width=3)
    paint.text((120, 90), 'HELLO THERE', font=ImageFont.truetype(str(FONT), 24), fill='black')
    region = TextRegion(1, (110, 80, 180, 60), bubble_bbox=(25, 15, 345, 210), text='HELLO THERE', translation='Привет!')
    prepare_regions(image, [region])
    assert region.auto_layout.get('contour')
    original_area = interior_mask(np.asarray(image), region)
    cleaned_area = interior_mask(np.asarray(Image.new('RGB', image.size, 'black')), region)
    assert np.array_equal(original_area, cleaned_area)
    assert np.count_nonzero(cleaned_area) > 180 * 60


def test_untranslated_target_is_reported():
    from src.config import Config
    from src.page_pipeline import PagePipeline
    from tests.integration.test_page_pipeline import FakeDetector, FakeOcr
    class EmptyTranslator:
        def translate(self, image, regions, *args, **kwargs):
            return regions
    pipeline = PagePipeline(Config(layout_long_side=0), detector=FakeDetector(), ocr=FakeOcr(), translator=EmptyTranslator())
    result = pipeline.analyze(Image.new('RGB', (200, 120), 'white'), '', 'en', 'ru')
    assert result.regions
    assert any('Не переведены' in warning for warning in result.warnings)


def test_narration_without_balloon_keeps_free_text_role():
    image = Image.new('RGB', (300, 160), 'white')
    ImageDraw.Draw(image).text((30, 40), 'A full thought here', font=ImageFont.truetype(str(FONT), 24), fill='black')
    region = TextRegion(1, (20, 30, 260, 70), class_name='text_bubble', block_type='narration',
                        text='A full thought here', translation='Полная мысль героя')
    prepare_regions(image, [region])
    assert region.auto_layout['kind'] == 'free'


def test_partial_white_patch_cannot_swallow_the_rest_of_a_phrase():
    from src.components.adaptive_text import inferred_balloon_area
    image = Image.new('RGB', (240, 140), (100, 100, 100))
    ImageDraw.Draw(image).rectangle((20, 20, 105, 100), fill='white')
    ink = np.zeros((80, 180), np.uint8)
    ink[20:50, 10:40] = 255
    ink[20:50, 130:160] = 255
    region = TextRegion(1, (20, 20, 180, 80), text='Complete phrase')
    area = inferred_balloon_area(image, region, ink, (20, 20, 200, 100))
    assert area[50, 165] > 0


def test_legacy_layout_key_stays_valid_without_optional_metadata():
    import json
    from src.components.typesetter import _layout_key, _frozen_layout
    region = TextRegion(1, (20, 20, 100, 60), translation='Старый проект')
    key = _layout_key(region)
    assert 'auto_layout' not in json.loads(key)
    region.layout_snapshot = dict(version=1, layout_key=key, font_size=12,
                                  lines=[['Старый проект', 25, 30]], font='Heroika-Regular.otf')
    restored = TextRegion.from_dict(region.to_dict())
    assert _frozen_layout(restored)['font_size'] == 12


def test_free_manual_spacing_does_not_drift_after_snapshot():
    region = TextRegion(1, (30, 30, 240, 120), translation='Тихая\nфраза', block_type='narration',
                        style=TextStyle(font_id='Heroika-Regular', letter_spacing=2, line_spacing=3),
                        auto_layout=dict(version=1, kind='free', source_bbox=[30, 30, 240, 120],
                                         ink_bbox=[30, 30, 240, 120], outline_px=3))
    image = Image.new('RGB', (350, 200), 'white')
    setter = Typesetter()
    first, _ = setter.render(image, [region])
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    second, _ = setter.render(image, [region])
    third, _ = setter.render(image, [region])
    assert np.array_equal(np.asarray(first), np.asarray(second))
    assert np.array_equal(np.asarray(second), np.asarray(third))


def test_adaptive_mask_grows_by_one_pixel():
    image = Image.new('RGB', (160, 100), 'white')
    paint = ImageDraw.Draw(image)
    paint.rectangle((40, 30, 44, 65), fill='black')
    sound = TextRegion(1, (38, 28, 9, 40), block_type='sfx', text='BAM', translation='БАМ')
    speech = TextRegion(2, (53, 28, 40, 40), text='Hello', translation='Привет', bubble_bbox=(50, 20, 50, 60))
    prepare_regions(image, [sound, speech])
    other = np.zeros((100, 160), np.uint8)
    _, base = adaptive_masks(image, [sound, speech], other, other.copy(), grow_px=0)
    _, grown = adaptive_masks(image, [sound, speech], other, other.copy(), grow_px=1)
    assert int(np.sum(grown > 0)) > int(np.sum(base > 0))
    assert np.all((base > 0) <= (grown > 0))
    assert not np.any(grown[28:68, 53:93])


def test_clean_upscale_does_not_invalidate_existing_auto_snapshot():
    from src.config import Config
    from src.page_pipeline import PagePipeline
    from src.components.typesetter import _frozen_layout
    class IdentityPainter:
        def inpaint(self, image, mask, **kwargs):
            return image.copy()
    image = Image.new('RGB', (697, 482), 'white')
    region = TextRegion(1, (20, 30, 200, 100), text='WORDS', translation='Слова',
                        style=TextStyle(font_id='Heroika-Regular'),
                        auto_layout=dict(version=1, kind='bubble', source_bbox=[20, 30, 200, 100],
                                         ink_bbox=[20, 30, 200, 100], outline_px=3., mask_pad_px=8.,
                                         contour=[[20, 30], [220, 30], [220, 130], [20, 130]]))
    setter = Typesetter()
    setter.render(image, [region])
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    pipeline = PagePipeline(Config(layout_long_side=2000), inpainter=IdentityPainter())
    pipeline.clean(image, [region])
    assert _frozen_layout(region) is not None
