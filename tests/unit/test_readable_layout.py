"""Регрессии потери реплики, неполного контура и автоматической обводки."""
import copy
import cv2
import numpy as np
from PIL import Image, ImageDraw
from src.models import TextRegion, TextStyle
from src.components.adaptive_text import geometry_area
from src.components.typesetter import Typesetter, _complete_fallback, _font_file
from src.components.bubble_layout import light_layout_area, balloon_body


def test_automatic_balloon_scale_keeps_complete_text_inside_shape():
    """Увеличение кегля после подбора не выталкивает буквы из облачка."""
    from src.components.typesetter import interior_mask
    image = np.full((180, 300, 3), 80, np.uint8)
    cv2.ellipse(image, (150, 90), (135, 75), 0, 0, 360, (255, 255, 255), -1)
    region = TextRegion(1, (45, 40, 210, 100), bubble_bbox=(15, 15, 270, 150),
        translation='ДЛИННАЯ РЕПЛИКА ДОЛЖНА ПОЛНОСТЬЮ ПОМЕЩАТЬСЯ В ОБЛАЧКО',
        block_type='dialogue', auto_layout=dict(version=1, kind='bubble'))
    setter = Typesetter(min_font_size=8, max_font_size=80, font_scale=1.35)
    _, overflow = setter.render(Image.fromarray(image), [region])
    assert not overflow
    area = balloon_body(interior_mask(image, region), region)
    alpha = np.asarray(setter._last_overlay)[..., 3]
    assert not np.any((alpha > 20) & (area == 0))
    drawn = ''.join(line for line, _, _ in setter._last_layouts[1]['lines'])
    assert drawn.replace(' ', '').replace('-', '') == region.translation.replace(' ', '')


def test_partial_first_line_contour_is_rejected():
    region = TextRegion(1, (30, 30, 140, 80), bubble_bbox=(10, 10, 180, 120),
                        auto_layout={'version': 1, 'kind': 'bubble',
                                     'contour': [[30, 30], [170, 30], [170, 48], [30, 48]]})
    assert geometry_area((140, 200), region) is None
    image = np.full((140, 200, 3), 70, np.uint8)
    cv2.ellipse(image, (100, 70), (86, 56), 0, 0, 360, (235, 235, 235), -1)
    partial = np.zeros((140, 200), np.uint8)
    partial[30:49, 30:170] = 255
    area = light_layout_area(image, region, partial)
    assert np.mean(area[30:110, 30:170] > 0) > .9


def test_emergency_layout_keeps_every_word():
    region = TextRegion(1, (20, 20, 130, 45), translation='Мы можем лишь надеяться на это!')
    draw = ImageDraw.Draw(Image.new('RGB', (180, 100)))
    placed, font = _complete_fallback(region.translation, region, _font_file(region), draw,
                                     None, 10, 0, 0, lambda size: 1)
    assert ' '.join(line for line, _, _ in placed) == region.translation
    assert font.size > 0


def test_flat_colored_balloon_has_no_halo_and_manual_modes_survive():
    image = Image.new('RGB', (250, 150), (100, 130, 170))
    region = TextRegion(1, (35, 40, 180, 65), bubble_bbox=(10, 10, 230, 130),
                        text='Hello', translation='Привет',
                        auto_layout={'version': 1, 'kind': 'bubble'},
                        style=TextStyle(font_size_override=28))
    setter = Typesetter(stroke_ratio=.08)
    result, overflow = setter.render(image, [region])
    assert not overflow
    pixels = np.array(result)
    assert np.count_nonzero(np.all(pixels > 245, axis=2)) == 0
    assert np.count_nonzero(np.all(pixels < 40, axis=2)) > 20
    for mode, width in [('none', 0), ('custom', 3)]:
        manual = copy.deepcopy(region)
        manual.style.stroke_mode = mode
        manual.style.stroke_width = 3
        manual.style.stroke_rgb = (200, 10, 20)
        area = np.full((150, 250), 255, np.uint8)
        color, actual = setter._stroke_paint(np.array(image), area, manual, 28)
        assert actual == width
        if mode == 'custom':
            assert color == (200, 10, 20)


def test_thin_tail_does_not_set_balloon_body_center():
    mask = np.zeros((140, 240), np.uint8)
    cv2.ellipse(mask, (150, 65), (65, 48), 0, 0, 360, 255, -1)
    cv2.line(mask, (90, 70), (12, 128), 255, 5)
    region = TextRegion(1, (110, 40, 80, 50), bubble_bbox=(10, 10, 210, 120))
    body = balloon_body(mask, region)
    assert not body[127, 13]
    assert np.all(body[40:90, 110:190])


def test_overflow_at_minimum_does_not_clip_letters():
    """Если после сжатия интервалов текст всё ещё не влезает, буквы не клипаются маской."""
    image = Image.new('RGB', (220, 70), 'white')
    region = TextRegion(
        1, (10, 10, 70, 22),
        translation='Очень длинная подпись которая не помещается в узкую полосу',
        document=True,
    )
    result, overflow = Typesetter(min_font_size=10, max_font_size=10, font_scale=1.0).render(
        image, [region], force=True,
    )
    assert overflow == [1]
    assert region.style.font_size >= 10
    changed = np.any(np.asarray(result) != 255, axis=2)
    area = np.zeros((70, 220), np.uint8)
    x, y, w, h = region.bbox
    area[y:y+h, x:x+w] = 255
    assert np.any(changed & (area == 0))


def test_narrow_balloon_keeps_horizontal_russian():
    """Горизонтальный перевод в узком баллоне не ставится вертикально."""
    from src.components.adaptive_text import prepare_regions

    image = Image.new('RGB', (160, 280), (30, 30, 30))
    ImageDraw.Draw(image).ellipse((50, 20, 110, 260), fill=(250, 250, 250))
    ImageDraw.Draw(image).text((62, 70), 'Hi!', fill=(10, 10, 10))
    region = TextRegion(
        1, (58, 60, 44, 40),
        bubble_bbox=(50, 20, 60, 240),
        text='Hi!',
        translation='Привет всем',
        block_type='dialogue',
        class_name='text_bubble',
    )
    prepare_regions(image, [region])
    assert (region.auto_layout or {}).get('writing_mode') != 'vertical'


def test_textured_balloon_keeps_automatic_outline():
    """На неоднородном рисунке сохраняется контрастный край букв."""
    region = TextRegion(1, (10, 10, 100, 60), translation='Текст',
                        auto_layout=dict(kind='bubble'))
    image = np.full((80, 140, 3), 230, np.uint8)
    image[:, ::2] = 70
    area = np.full((80, 140), 255, np.uint8)
    assert Typesetter()._stroke_paint(image, area, region, 28)[1] > 0
    image[:] = 160
    assert Typesetter()._stroke_paint(image, area, region, 28)[1] == 0
    region.auto_layout['source_outline'] = True
    assert Typesetter()._stroke_paint(image, area, region, 28)[1] > 0


def test_smooth_gradient_does_not_require_a_halo():
    """Широкий диапазон серого сам по себе не означает пёстрый рисунок."""
    from src.components.typesetter import _background_is_complex
    gradient = np.tile(np.linspace(90, 220, 240, dtype=np.uint8), (100, 1))
    image = np.repeat(gradient[..., None], 3, axis=2)
    area = np.full((100, 240), 255, np.uint8)
    assert not _background_is_complex(image, area)


def test_confirmed_light_caption_keeps_dark_outline_on_medium_background():
    """Финальная растеризация не меняет светлое ядро на чёрное из-за фона."""
    for kind in ['free', 'bubble']:
        image = Image.new('RGB', (360, 180), (125, 145, 180))
        region = TextRegion(1, (30, 40, 300, 100), translation='СВЕТЛЫЙ ТЕКСТ',
                            block_type='dialogue',
                            auto_layout=dict(version=1, kind=kind, ink_bbox=[30, 40, 300, 100],
                                             source_fill=[205, 210, 255], source_outline=True),
                            style=TextStyle(fill_rgb=(205, 210, 255), stroke_rgb=(10, 10, 20),
                                            font_size_override=28))
        setter = Typesetter(stroke_ratio=.08)
        result, _ = setter.render(image, [region])
        assert region.style.fill_rgb == (205, 210, 255)
        pixels = np.asarray(result)
        assert np.count_nonzero(np.max(np.abs(pixels.astype(int) - (205, 210, 255)), axis=2) < 12) > 30
        assert np.count_nonzero(np.max(np.abs(pixels.astype(int) - (10, 10, 20)), axis=2) < 12) > 10


def test_manual_paint_overrides_confirmed_source_pair():
    """Подтверждение исходника не отменяет ручные цвет и обводку."""
    from src.components.typesetter import _source_paint
    region = TextRegion(1, (0, 0, 100, 50),
                        auto_layout=dict(source_fill=[205, 210, 255], source_outline=True),
                        style=TextStyle(fill_rgb=(200, 20, 30), fill_locked=True,
                                        stroke_rgb=(0, 0, 0)))
    assert _source_paint(region) is None
    region.style.fill_locked = False
    region.style.stroke_mode = 'custom'
    assert _source_paint(region) is None
