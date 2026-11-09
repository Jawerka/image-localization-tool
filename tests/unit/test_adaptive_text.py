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


def test_inferred_balloon_keeps_word_outside_contour():
    """Чернила в кропе inferred-облачка не вырезаются узкой оболочкой."""
    rgb = np.full((180, 280, 3), (40, 40, 45), np.uint8)
    cv2.ellipse(rgb, (90, 80), (70, 45), 0, 0, 360, (250, 250, 250), -1)
    cv2.ellipse(rgb, (90, 80), (70, 45), 0, 0, 360, (10, 10, 10), 2)
    cv2.putText(rgb, "ASK", (55, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
    cv2.putText(rgb, "WHEW", (175, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (250, 250, 250), 2)
    image = Image.fromarray(rgb)
    region = TextRegion(
        1, (20, 30, 230, 100), text="ASK WHEW", translation="А",
        block_type="dialogue", class_name="text_bubble",
        auto_layout=dict(
            version=1, kind="bubble", source_bbox=[20, 30, 230, 100],
            ink_bbox=[20, 30, 230, 100], outline_px=3, mask_pad_px=8,
            contour=[[22, 36], [158, 36], [158, 124], [22, 124]],
        ),
    )
    other = np.zeros(rgb.shape[:2], np.uint8)
    other, _free = adaptive_masks(image, [region], other, np.zeros_like(other))
    whew = np.zeros(rgb.shape[:2], np.uint8)
    cv2.putText(whew, "WHEW", (175, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
    assert np.mean(other[whew > 0] > 0) >= 0.45


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
    setter = Typesetter(min_font_size=10, max_font_size=128)
    _, overflow = setter.render(Image.new('RGB', (100, 40), 'white'), [region], force=True)
    assert region.style.font_size >= 10
    laid = ''.join(line for line, _, _ in setter._last_layouts[1]['lines']).replace('-', '')
    assert laid.replace(' ', '') == 'Подписаться'
    assert overflow in ([], [1])


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


@pytest.mark.parametrize('background,expected', [((248, 248, 248), 3), ((128, 128, 128), 5)])
def test_native_outline_survives_working_upscale(background, expected):
    from src.config import Config
    from src.page_pipeline import PagePipeline
    image = Image.new('RGB', (400, 250), background)
    original = TextRegion(1, (100, 60, 80, 120), text='THUD', translation='I', block_type='sfx',
                          style=TextStyle(fill_rgb=(18, 18, 18), font_id='Heroika-Regular'),
                          auto_layout=dict(version=1, kind='free', source_bbox=[100, 60, 80, 120],
                                           ink_bbox=[100, 60, 80, 120], outline_px=3, mask_pad_px=8))
    widths = []
    for side in (0, 2000):
        # Проверяется толщина обводки, увеличение букв проверяется отдельно.
        pipeline = PagePipeline(Config(layout_long_side=side, text_scale=1.0))
        rendered, over = pipeline.typeset_image(image, [copy.deepcopy(original)], 'en')
        assert not over
        row = np.asarray(rendered)[120, :, 0]
        black = np.flatnonzero(row < 60)
        white = np.flatnonzero(row > 250)
        widths.append((black[0] - white[0], white[-1] - black[-1]))
    assert all(expected - 1 <= value <= expected + 1 for pair in widths for value in pair), widths
    assert all(abs(a - b) <= 1 for a, b in zip(*widths)), widths


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


def _paint_caption(canvas, text, xy, angle, fill, stroke):
    font = ImageFont.truetype(str(FONT), 34)
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=fill, stroke_width=3, stroke_fill=stroke)
    cx, cy = xy[0] + 90, xy[1] + 18
    return Image.alpha_composite(canvas, layer.rotate(angle, resample=Image.BICUBIC, center=(cx, cy)))


def test_texture_captions_need_steep_angle_for_free_style():
    from src.components.font_catalog import assign_stylized_fonts

    canvas = Image.new('RGBA', (520, 280), (38, 32, 28, 255))
    noise = np.random.default_rng(3).integers(0, 28, (280, 520, 3), dtype=np.uint8)
    base = np.asarray(canvas.convert('RGB'))
    canvas = Image.fromarray(np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)).convert('RGBA')
    canvas = _paint_caption(canvas, 'P-PRINCESS', (40, 50), 2.6, (255, 220, 40, 255), (20, 12, 0, 255))
    canvas = _paint_caption(canvas, 'OH WHAT', (40, 150), 22.0, (255, 220, 40, 255), (20, 12, 0, 255))
    image = canvas.convert('RGB')
    mild = TextRegion(1, (30, 30, 240, 80), text='P-PRINCESS', translation='П-ПРИНЦЕССА',
                      block_type='dialogue', class_name='text_bubble')
    steep = TextRegion(2, (30, 130, 220, 80), text='OH WHAT', translation='Ой, что это?',
                       block_type='dialogue', class_name='text_bubble')
    mild._retouch_preserve_background = True
    steep._retouch_preserve_background = True
    prepare_regions(image, [mild, steep])
    assert mild.auto_layout['kind'] == 'bubble'
    assert steep.auto_layout['kind'] == 'free'
    assign_stylized_fonts([mild, steep])
    assert mild.style.font_id == 'Heroika-Regular'
    assert steep.style.font_id


def test_shallow_balloon_angle_snaps_to_upright():
    image = Image.new('RGB', (420, 280), (40, 40, 45))
    paint = ImageDraw.Draw(image)
    paint.ellipse((30, 30, 390, 250), fill=(250, 250, 250), outline=(10, 10, 10), width=3)
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((90, 110), 'HELLO THERE FRIEND', font=ImageFont.truetype(str(FONT), 28), fill=(10, 10, 10, 255))
    image = Image.alpha_composite(image.convert('RGBA'), layer.rotate(2.6, resample=Image.BICUBIC, center=(210, 140))).convert('RGB')
    region = TextRegion(1, (80, 90, 260, 80), text='HELLO THERE FRIEND', translation='Привет друг',
                        bubble_bbox=(25, 25, 370, 230), block_type='dialogue', class_name='text_bubble')
    prepare_regions(image, [region])
    assert region.auto_layout['kind'] == 'bubble'
    assert region.style.rotation == 0
    assert region.auto_layout['angle'] == 0


def test_outlined_free_mask_gains_two_pixels_without_growing_balloon():
    rgb = np.full((140, 260, 3), (30, 30, 35), np.uint8)
    cv2.putText(rgb, 'BAM', (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 10)
    cv2.putText(rgb, 'BAM', (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3)
    cv2.ellipse(rgb, (190, 70), (50, 35), 0, 0, 360, (250, 250, 250), -1)
    cv2.putText(rgb, 'Hi', (170, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (10, 10, 10), 2)
    image = Image.fromarray(rgb)
    sound = TextRegion(1, (20, 40, 110, 70), block_type='sfx', text='BAM', translation='БАМ')
    speech = TextRegion(2, (155, 45, 70, 50), text='Hi', translation='Привет',
                        bubble_bbox=(138, 32, 105, 78), block_type='dialogue')
    sound._outline_ink = True
    prepare_regions(image, [sound, speech])
    assert sound.auto_layout['kind'] == 'free'
    assert speech.auto_layout['kind'] == 'bubble'
    assert sound.auto_layout['mask_pad_px'] == speech.auto_layout['mask_pad_px'] + 2
    empty = np.zeros((140, 260), np.uint8)
    other_with, free_with = adaptive_masks(image, [sound, speech], empty, empty.copy())
    sound.auto_layout['mask_pad_px'] -= 2
    other_without, free_without = adaptive_masks(image, [sound, speech], empty, empty.copy())
    extra = (free_with > 0) & (free_without == 0)
    assert np.count_nonzero(extra) > 0
    dist = cv2.distanceTransform((free_without == 0).astype(np.uint8), cv2.DIST_L2, 5)
    assert float(np.median(dist[extra])) >= 1.0
    assert np.array_equal(other_with, other_without)


@pytest.mark.parametrize('angle', [-25, 0, 25])
def test_speech_angle_confirms_real_rows(angle):
    """Настоящий наклон строк сохраняется после проверки компонентов."""
    from src.components.adaptive_text import speech_angle
    layer = Image.new('L', (500, 220))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT), 30)
    for y in (25, 85, 145):
        draw.text((30, y), 'Several words in a line', font=font, fill=255)
    result, _ = speech_angle(np.array(layer.rotate(angle, expand=True)))
    assert abs(result-angle) <= 2


def test_speech_angle_ignores_larger_slanted_neighbor():
    """Крупный звук рядом не задаёт угол горизонтальной реплики."""
    from src.components.adaptive_text import speech_angle
    layer = Image.new('L', (500, 240))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT), 24)
    for y, text in zip((20, 52, 84, 116), ('N-No, I must not!', 'What am I', 'thinking about', 'right now?!')):
        draw.text((240, y), text, font=font, fill=255)
    neighbor = Image.new('L', (200, 70))
    ImageDraw.Draw(neighbor).text((0, 0), 'SHAKE', font=ImageFont.truetype(str(FONT), 48), fill=255)
    neighbor = neighbor.rotate(26, expand=True)
    layer.paste(neighbor, (0, 80), neighbor)
    angle, _ = speech_angle(np.array(layer))
    assert abs(angle) < 3


def test_short_slanted_speech_with_tall_capitals_keeps_rotation():
    """Семь сопоставимых букв достаточны, даже если прописные выше строки."""
    from src.components.adaptive_text import speech_angle
    layer = Image.new('L', (500, 180))
    draw = ImageDraw.Draw(layer)
    for i in range(7):
        draw.rectangle((30+i*45, 80, 43+i*45, 109), fill=255)
    for i in range(3):
        draw.rectangle((350+i*45, 50, 363+i*45, 109), fill=255)
    angle, _ = speech_angle(np.array(layer.rotate(12, expand=True)))
    assert abs(angle-12) < 2


def test_coloured_caption_keeps_two_slanted_rows_and_balloon_mask():
    """Цветная карточка использует строки букв, сохраняя прежний путь очистки."""
    from src.config import Config
    from src.page_pipeline import PagePipeline

    class IdentityPainter:
        def inpaint(self, image, mask):
            return image

    canvas = Image.new('RGBA', (640, 260), (65, 60, 75, 255))
    layer = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT), 32)
    for y, text in [(65, 'FIRST COLOURED LINE'), (135, 'SECOND COLOURED LINE')]:
        draw.text((60, y), text, font=font, fill='white', stroke_width=3, stroke_fill=(30, 200, 210))
    image = Image.alpha_composite(canvas, layer.rotate(-11, resample=Image.BICUBIC)).convert('RGB')
    region = TextRegion(1, (25, 25, 590, 210), text='FIRST COLOURED LINE SECOND COLOURED LINE',
                        translation='Первая цветная строка Вторая цветная строка',
                        block_type='dialogue', bubble_bbox=(10, 10, 620, 240))
    pipeline = PagePipeline(Config(layout_long_side=0, ocr_backend='rapid'), inpainter=IdentityPainter())
    mask, _ = pipeline.clean(image, [region])
    assert np.count_nonzero(mask) > 100
    assert region.auto_layout['kind'] == 'free'
    assert region.auto_layout['mask_kind'] == 'bubble'
    assert len(region.auto_layout['source_lines']) == 2
    assert abs(region.style.rotation + 11) < 2
    assert TextRegion.from_dict(region.to_dict()).auto_layout == region.auto_layout


def test_unbound_slanted_speech_cleans_each_large_word():
    """Оболочка строк не обрезает отдельные крупные буквы наклонной речи."""
    from src.components.adaptive_text import source_ink
    size = (780, 360)
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).ellipse((10, 5, 770, 350), outline='black', width=3)
    font = ImageFont.truetype(str(FONT), 60)
    words = []
    for text, xy in [('LOOK', (100, 70)), ('WHAT', (365, 70)), ('I HAVE', (100, 155)), ('FOR YOU!', (365, 155))]:
        layer = Image.new('L', size)
        ImageDraw.Draw(layer).text(xy, text, font=font, fill=255, stroke_width=1)
        layer = layer.rotate(9, resample=Image.BICUBIC, center=(390, 180))
        words.append(np.asarray(layer) > 220)
        image.paste('black', mask=layer)
    region = TextRegion(1, (60, 20, 640, 270), text='LOOK WHAT I HAVE FOR YOU!',
                        translation='СМОТРИ, ЧТО У МЕНЯ ДЛЯ ТЕБЯ!',
                        block_type='dialogue', class_name='text_bubble')
    prepare_regions(image, [region])
    _, ink, (a, b, c, d) = source_ink(image, region)
    empty = np.zeros((size[1], size[0]), np.uint8)
    ordinary, free = adaptive_masks(image, [region], empty, empty.copy())
    for word in words:
        assert np.mean(ink[word[b:d, a:c]] > 0) >= .99
        assert np.mean(np.maximum(ordinary, free)[word] > 0) >= .99


def test_speech_row_height_ignores_many_small_texture_components():
    """Много мелких пятен не обрезают крайние буквы подтверждённых строк."""
    from src.components.adaptive_text import _supported_speech_rows
    layer = Image.new('L', (650, 260))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT), 54)
    draw.text((190, 60), 'LOOK WHAT', font=font, fill=255)
    draw.text((190, 150), 'FOR YOU!', font=font, fill=255)
    layer = layer.rotate(9, resample=Image.BICUBIC, center=(325, 130))
    letters = np.asarray(layer) > 220
    ink = np.array(layer)
    for y in range(0, 55, 8):
        for x in range(0, 170, 8):
            ink[y:y+5, x:x+3] = 255
    filtered = _supported_speech_rows(ink)
    assert np.mean(filtered[letters] > 0) >= .99
