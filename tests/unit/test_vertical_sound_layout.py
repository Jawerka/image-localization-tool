"""Вертикальное письмо, тонкие встроенные звуки и внешняя обводка."""
import copy
from pathlib import Path
import numpy as np
from PIL import Image, ImageFont
from src.models import TextRegion, TextStyle
from src.components.font_catalog import assign_stylized_fonts, scan_fonts
from src.components.free_text_layout import free_raster
from src.components.glyph_layout import vertical_glyph_mask
from src.components.typesetter import Typesetter

FONT = Path(__file__).resolve().parents[2] / 'src/resources/fonts/Jupiteroid-Light.ttf'

def test_vertical_glyph_order_and_word_gap():
    font = ImageFont.truetype(str(FONT), 80)
    actual = vertical_glyph_mask('Ш ИН', font, line_spacing=12)
    rows = np.flatnonzero(np.any(np.array(actual) > 0, axis=1))
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    assert len(groups) == 3
    assert groups[1][0] - groups[0][-1] > groups[2][0] - groups[1][-1]
    for ch, group in zip('ШИН', groups):
        expected = vertical_glyph_mask(ch, font, line_spacing=12)
        crop = actual.crop((0, int(group[0]), actual.width, int(group[-1])+1))
        assert np.array_equal(np.array(crop.crop(crop.getbbox())),
                              np.array(expected.crop(expected.getbbox())))

def test_auto_vertical_requires_short_tall_sound_and_snapshot_is_stable():
    style = TextStyle(font_size=20)
    meta = dict(version=1, kind='free', ink_bbox=[20,20,45,240],
                source_bbox=[20,20,45,240], allow_vertical=True)
    layer, fit = free_raster('ШУРХ!', FONT, style, meta)
    assert fit['writing_mode'] == 'vertical'
    assert fit['text'] == 'ШУРХ!'
    same, repeated = free_raster('ШУРХ!', FONT, style, meta, frozen=fit)
    assert np.array_equal(np.array(layer), np.array(same))
    assert repeated == fit
    for change in [dict(allow_vertical=False), dict(ink_bbox=[20,20,240,45])]:
        _, horizontal = free_raster('ШУРХ!', FONT, style, dict(meta, **change))
        assert horizontal['writing_mode'] == 'horizontal'

def test_explicit_vertical_preserves_text_and_roundtrips():
    region = TextRegion(1,(20,20,70,260), text='RUSTLE', translation='ШУРХ ШУРХ!',
        block_type='sfx', style=TextStyle(font_id='Jupiteroid-Light'),
        auto_layout=dict(version=1,kind='free',writing_mode='vertical',
                         source_bbox=[20,20,70,260],ink_bbox=[20,20,70,260]))
    image = Image.new('RGB',(130,330),(90,105,120))
    setter = Typesetter()
    rendered, overflow = setter.render(image,[region])
    assert not overflow
    region.layout_snapshot = copy.deepcopy(setter._last_layouts[1])
    assert region.layout_snapshot['raster_fit']['writing_mode'] == 'vertical'
    loaded = TextRegion.from_dict(region.to_dict())
    repeated, _ = setter.render(image,[loaded])
    assert np.array_equal(np.array(rendered),np.array(repeated))
    assert loaded.translation == 'ШУРХ ШУРХ!'
    pixels=np.array(rendered)
    assert np.count_nonzero(np.all(pixels > 245,axis=2)) > 30
    # Обводка окружает буквы; ни один белый пиксель не обрезан краем кадра.
    assert not np.any(np.all(pixels[[0,-1],:] > 245,axis=2))

def test_bundled_light_sound_font_and_manual_override():
    region = TextRegion(1,(0,0,40,200),block_type='sfx',translation='БАХ',
                        auto_layout={'kind':'free','version':1})
    faces=scan_fonts(include_system=False)
    assign_stylized_fonts([region],faces=faces)
    assert region.style.font_id == 'Jupiteroid-Light'
    region.style.font_id='Liber-Struct'
    assign_stylized_fonts([region],faces=faces)
    assert region.style.font_id=='Liber-Struct'


def test_outline_fallback_completes_partial_box_and_protects_neighbour():
    from PIL import ImageDraw
    from src.components.text_discovery import _refine_outlined_sfx
    image=Image.new('RGB',(450,200),(155,155,155))
    font=ImageFont.truetype(str(FONT.parent/'Heroika-Regular.otf'),42)
    ImageDraw.Draw(image).text((130,70),'HAH',font=font,fill='black',stroke_fill='white',stroke_width=3)
    sound=TextRegion(1,(100,70,60,60),text='HAH',block_type='sfx')
    original=copy.deepcopy(sound)
    _refine_outlined_sfx(image,sound,[])
    assert sound.bbox[0]>=125
    assert sound.bbox[0]+sound.bbox[2]>170
    neighbour=TextRegion(2,sound.bbox,text='other')
    _refine_outlined_sfx(image,original,[neighbour])
    assert original.bbox==(100,70,60,60)

def test_vertical_balloon_respects_taper_and_outline():
    from src.components.typesetter import interior_mask
    region=TextRegion(1,(40,50,35,50),translation='П-подожди...',
        bubble_bbox=(30,10,60,240),style=TextStyle(font_id='Heroika-Regular'),
        auto_layout=dict(version=1,kind='bubble',writing_mode='vertical',source_bbox=[40,50,35,50],
            ink_bbox=[36,16,48,228],outline_px=3,
            contour=[[60,14],[85,55],[86,200],[60,245],[35,200],[35,55]]))
    image=Image.new('RGB',(130,280),'white')
    setter=Typesetter()
    _,overflow=setter.render(image,[region],force=True)
    assert not overflow
    area=interior_mask(np.array(image),region)
    assert not np.any((np.array(setter._last_overlay)[...,3]>20)&(area==0))

def test_fallback_core_is_bounded_and_retained_when_source_exceeds_balloon():
    from PIL import ImageDraw
    from src.components.adaptive_text import geometry_area
    image=Image.new('RGB',(260,280),(80,80,80))
    paint=ImageDraw.Draw(image)
    paint.rectangle((30,20,130,260),fill='white')
    for y in range(20,260,12):
        paint.line((130,y,180,y-15),fill='white',width=3)
    region=TextRegion(1,(40,50,145,180),bubble_bbox=(25,15,160,250),translation='Это пример текста',block_type='dialogue')
    # Проверяем сам запасной путь: обычный детектор силуэта может его опередить.
    from src.components.bubble_layout import fallback_light_core
    area=fallback_light_core(np.array(image),region)
    assert area is not None
    assert area[120,80] and not area[120,175]
    region.auto_layout=dict(version=1,kind='bubble',contour_source='light_core',
        contour=[[30,20],[130,20],[130,260],[30,260]])
    assert geometry_area((280,260),region) is not None
    region.auto_layout['contour']=[[0,0],[10,0],[10,10],[0,10]]
    assert geometry_area((280,260),region) is None


def test_lowercase_source_leak_is_caught_below_foreign_share_threshold():
    from src.components.lang_guard import unchanged_foreign_words,foreign_leak
    source='Rumors about Yanfei spread like wildfire in the harbor.'
    translation='В тот день слухи о Яньфэй разлетелись по всей гавани словно wildfire.'
    assert not foreign_leak(translation,'ru')
    assert unchanged_foreign_words(source,translation,'ru')
    assert not unchanged_foreign_words(source,translation,'ru',['wildfire'])
    assert not unchanged_foreign_words(source,'Слухи о Yanfei быстро разлетелись по гавани.','ru')


def test_plain_cjk_group_recovers_missing_large_sign_and_protects_speech():
    from PIL import ImageDraw
    from src.components.text_discovery import _refine_plain_cjk_sfx
    image=Image.new('RGB',(400,220),'white')
    font=ImageFont.truetype(str(FONT.parent/'Heroika-Regular.otf'),100)
    ImageDraw.Draw(image).text((45,40),'HA',font=font,fill='black')
    region=TextRegion(1,(100,20,100,140),text='\u3069\u3084',block_type='sfx')
    original=copy.deepcopy(region)
    _refine_plain_cjk_sfx(image,region,[])
    assert region.bbox[0]<60 and region.bbox[0]+region.bbox[2]>165
    speech=TextRegion(2,(45,30,60,100),text='speech')
    _refine_plain_cjk_sfx(image,original,[speech])
    assert original.bbox==(100,20,100,140)
