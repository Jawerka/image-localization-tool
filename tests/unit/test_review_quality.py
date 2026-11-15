"""Регрессии по ручной оценке прогона full-review-20261114."""
import copy

import numpy as np
from PIL import Image, ImageFont

from src.components.free_text_layout import free_raster
from src.components.retouch_ink import fill_flat_dialogue
from src.components.typesetter import COMIC_FONT, Typesetter
from src.models import TextRegion, TextStyle


def test_free_caption_uses_glyph_width_and_keeps_all_words():
    text = 'ШИРОКИЕ БУКВЫ И УЗКИЕ ЛИНИИ В ОДНОЙ НАДПИСИ'
    geometry = dict(kind='free', ink_bbox=[20, 20, 240, 100], source_bbox=[20, 20, 240, 100])
    style = TextStyle(stroke_mode='none')
    layer, fit = free_raster(text, COMIC_FONT, style, geometry)
    assert fit['text'].split() == text.split()
    bounds = layer.getchannel('A').getbbox()
    assert bounds[2]-bounds[0] <= 480 and bounds[3]-bounds[1] <= 200
    # Длинная единственная строка при равномерном масштабе даёт меньший кегль.
    font = ImageFont.truetype(str(COMIC_FONT), 144)
    assert fit['font_size'] > 144 * 240 / font.getlength(text)


def test_flat_coloured_retouch_preserves_unmasked_pixels_and_rejects_picture():
    rgb = np.full((100, 220, 3), (242, 213, 183), np.uint8)
    mask = np.zeros((100, 220), np.uint8)
    mask[35:55, 40:160:15] = 255
    rgb[mask > 0] = 20
    region = TextRegion(1, (20, 20, 180, 60), bubble_bbox=(10, 10, 200, 80), block_type='dialogue')
    clean, remaining = fill_flat_dialogue(Image.fromarray(rgb), mask, [region])
    assert not np.any(remaining)
    assert np.all(np.asarray(clean)[mask > 0] == (242, 213, 183))
    assert np.array_equal(np.asarray(clean)[mask == 0], rgb[mask == 0])
    textured = rgb.copy()
    textured[20:40, 20:200] = (120, 100, 80)
    clean, remaining = fill_flat_dialogue(Image.fromarray(textured), mask, [region])
    assert np.array_equal(remaining, mask)
    assert np.array_equal(np.asarray(clean), textured)


def test_neutral_auto_colours_are_stable_and_manual_colours_survive():
    region = TextRegion(1, (20, 20, 160, 60), translation='ПРИВЕТ', block_type='sfx',
                        style=TextStyle(fill_rgb=(240, 100, 200), stroke_mode='auto'),
                        auto_layout=dict(kind='free', ink_bbox=[20, 20, 160, 60], source_bbox=[20, 20, 160, 60]))
    for colour, expected in [((40, 30, 50), (255, 255, 255)), ((180, 190, 200), (0, 0, 0))]:
        current = copy.deepcopy(region)
        setter = Typesetter(neutral_text_colors=True)
        setter.render(Image.new('RGB', (220, 120), colour), [current])
        assert current.style.fill_rgb == expected
    current = copy.deepcopy(region)
    current.style.fill_locked = True
    Typesetter(neutral_text_colors=True).render(Image.new('RGB', (220, 120), 'gray'), [current])
    assert current.style.fill_rgb == region.style.fill_rgb


def test_thin_edge_outline_only_when_background_loses_contrast():
    from src.components.typesetter import _edge_contrast_outline
    layer = Image.new('RGBA', (30, 25))
    from PIL import ImageDraw
    ImageDraw.Draw(layer).rectangle((10, 5, 14, 20), fill=(0, 0, 0, 255))
    white = np.full((25, 30, 3), 255, np.uint8)
    assert _edge_contrast_outline(layer, (0, 0), white, (0, 0, 0), 30) is layer
    dark = white.copy()
    dark[15:] = 20
    edged = _edge_contrast_outline(layer, (0, 0), dark, (0, 0, 0), 30)
    assert np.asarray(edged)[10, 9, 3] > 0
    assert tuple(np.asarray(edged)[10, 12, :3]) == (0, 0, 0)
    # Та же проверка обратного цвета для белой буквы на светлом фоне.
    edged = _edge_contrast_outline(layer, (0, 0), white, (255, 255, 255), 30)
    assert tuple(np.asarray(edged)[10, 9, :3]) == (0, 0, 0)


def test_punctuation_does_not_get_thick_auto_stroke():
    region = TextRegion(1, (10, 10, 60, 20), translation='......', block_type='dialogue',
                        auto_layout=dict(kind='bubble', source_outline=False))
    assert Typesetter(stroke_ratio=.08)._fit_stroke_width(region, 24, True) == 0
    region.style.stroke_mode = 'custom'
    region.style.stroke_width = 3
    assert Typesetter()._fit_stroke_width(region, 24, True) == 3


def test_caption_reflows_noisy_source_rows_instead_of_shrinking_word():
    geometry = dict(kind='free', readable_caption=True, caption_padding=10,
                    source_bbox=[153, 1661, 264, 182], ink_bbox=[140, 1648, 290, 210],
                    source_lines=[[139, 1650, 303, 112], [167, 1766, 237, 57], [300, 1832, 87, 51]])
    _, fit = free_raster('2 минуты спустя:', COMIC_FONT,
                         TextStyle(rotation=21.2, stroke_mode='none'), geometry)
    assert fit['font_size'] > 20
    assert fit['text'].split() == ['2', 'минуты', 'спустя:']


def test_pipeline_keeps_flat_fill_when_no_model_work_remains(monkeypatch):
    import src.page_pipeline as pipeline_module
    from src.config import Config
    rgb = np.full((100, 220, 3), (242, 213, 183), np.uint8)
    mask = np.zeros((100, 220), np.uint8)
    mask[35:55, 40:160:15] = 255
    rgb[mask > 0] = 20
    region = TextRegion(1, (20, 20, 180, 60), bubble_bbox=(10, 10, 200, 80),
                        block_type='dialogue', text='Hello', translation='Привет')
    monkeypatch.setattr(pipeline_module, 'segment_regions',
                        lambda image, regions, **kwargs: mask.copy() if regions else np.zeros_like(mask))
    pipeline = pipeline_module.PagePipeline(Config(adaptive_text=False, ocr_backend='rapid', layout_long_side=0))
    def unexpected(*args, **kwargs):
        raise AssertionError('Залитое поле не должно отправляться модели ретуши')
    monkeypatch.setattr(pipeline, '_inpaint', unexpected)
    actual_mask, cleaned = pipeline.clean(Image.fromarray(rgb), [region])
    assert np.array_equal(actual_mask, mask)
    assert np.all(np.asarray(cleaned)[mask > 0] == (242, 213, 183))


def test_small_action_uses_readable_font_without_changing_manual_choice():
    region = TextRegion(1, (10, 10, 80, 30), translation='*нажимает*', block_type='sfx',
                        auto_layout=dict(kind='free', readable_action=True))
    assert Typesetter()._region_font(region) == COMIC_FONT
    region.edited = True
    assert Typesetter()._region_font(region) is not None


def test_tight_narration_box_does_not_become_an_ellipse():
    from src.components.adaptive_text import is_balloon
    narration = TextRegion(1, (20, 20, 218, 112), block_type='narration',
                           bubble_bbox=(22, 19, 217, 112))
    assert not is_balloon(narration)
    narration.block_type = 'dialogue'
    assert is_balloon(narration)


def test_separate_reply_does_not_inherit_neighbour_balloon():
    from PIL import ImageDraw
    from src.components.adaptive_text import prepare_regions
    image = Image.new('RGB', (300, 250), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(COMIC_FONT), 20)
    draw.text((40, 40), 'FIRST WORDS', font=font, fill='black')
    draw.text((110, 145), 'SECOND', font=font, fill='black')
    neighbour = TextRegion(1, (40, 40, 150, 30), text='FIRST WORDS', translation='Первая фраза',
                           block_type='dialogue', bubble_bbox=(30, 30, 170, 50))
    reply = TextRegion(2, (110, 145, 100, 30), text='SECOND', translation='Вторая фраза',
                       block_type='dialogue', bubble_bbox=(20, 20, 240, 180))
    prepare_regions(image, [neighbour, reply])
    assert reply.bubble_bbox is None
    assert reply.auto_layout['kind'] == 'free'
    assert neighbour.bubble_bbox == (30, 30, 170, 50)
