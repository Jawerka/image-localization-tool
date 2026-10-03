"""Вёрстка короткой фразы в прямоугольник и в баллон."""

import cv2
import numpy as np
from PIL import Image, ImageDraw

from src.components import typesetter as typesetter_module
from src.components.typesetter import Typesetter, interior_mask
from src.models import TextRegion, TextStyle


def test_document_line_changes_the_image():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        class_name="text_free",
        text="Hello",
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size=18),
    )
    result, overflow = Typesetter(min_font_size=12, max_font_size=28, lang="ru").render(image, [region])
    assert overflow == []
    dark = int(np.sum(np.any(np.array(result) != 255, axis=2)))
    assert dark > 20


def test_bubble_interior_stays_inside_the_outline():
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 150, 90), outline="black", width=3)
    region = TextRegion(
        id=1,
        bbox=(40, 35, 80, 30),
        bubble_bbox=(10, 10, 140, 80),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    mask = interior_mask(np.array(image), region)
    assert mask[50, 80] == 255
    assert mask[0, 0] == 0
    result, overflow = Typesetter(min_font_size=12, max_font_size=36).render(image, [region])
    assert result.size == image.size
    assert overflow == []


def test_dark_spot_does_not_punch_a_hole_in_interior():
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 150, 90), outline="black", width=3)
    draw.rectangle((96, 40, 116, 58), fill="black")
    region = TextRegion(
        id=1,
        bbox=(40, 35, 80, 30),
        bubble_bbox=(10, 10, 140, 80),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    mask = interior_mask(np.array(image), region)
    assert mask[49, 106] == 255
    assert mask[50, 80] == 255
    assert mask[0, 0] == 0


def test_halo_recolors_pixels_beside_letters():
    background = (250, 250, 250)
    image = Image.new("RGB", (240, 90), background)
    region = TextRegion(
        id=1,
        bbox=(10, 10, 220, 70),
        class_name="text_free",
        text="Hello",
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="center"),
    )
    setter = Typesetter(min_font_size=22, max_font_size=22, lang="ru", stroke_ratio=0.2)
    clean, overflow = setter.render(image, [region])
    assert overflow == []
    clean_arr = np.array(clean)
    dark = np.all(clean_arr < 60, axis=2)
    ring = (cv2.dilate(dark.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~dark
    assert int(ring.sum()) > 10

    dirty_arr = np.full_like(clean_arr, background)
    dirty_arr[ring] = (180, 180, 180)
    painted, overflow = setter.render(Image.fromarray(dirty_arr), [region])
    assert overflow == []
    painted_arr = np.array(painted)
    still_dirt = np.all(np.abs(painted_arr.astype(np.int16) - 180) <= 2, axis=2) & ring
    recolored = np.all(np.abs(painted_arr.astype(np.int16) - 250) <= 2, axis=2) & ring
    assert int(still_dirt.sum()) * 4 < int(ring.sum())
    assert int(recolored.sum()) > 10


def test_font_size_override_skips_binary_search(monkeypatch):
    calls = []
    real_load = typesetter_module._load_font

    def spy(path, size):
        calls.append(size)
        return real_load(path, size)

    monkeypatch.setattr(typesetter_module, "_load_font", spy)
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=7,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        overflow=True,
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=21),
    )
    empty = TextRegion(
        id=8,
        bbox=(10, 10, 40, 20),
        translation="",
        overflow=True,
    )
    _result, overflow = Typesetter(min_font_size=12, max_font_size=40, lang="ru").render(
        image, [region, empty]
    )
    assert calls == [21]
    assert region.overflow is (7 in overflow)
    assert empty.overflow is False


def _speech_bubble(phrase: str):
    image = Image.new("RGB", (360, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 344, 204), outline="black", width=4)
    region = TextRegion(
        id=1,
        bbox=(48, 48, 264, 124),
        bubble_bbox=(16, 16, 328, 188),
        translation=phrase,
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    return image, region


def test_margin_keeps_glyphs_inside_the_inset():
    from src.components.typesetter import inset_layout_mask, layout_inset_px

    phrase = "Это довольно длинная фраза для проверки запаса"
    image, region = _speech_bubble(phrase)
    margin = 0.08
    setter = Typesetter(min_font_size=10, max_font_size=48, lang="ru", margin_ratio=margin)
    result, overflow = setter.render(image, [region])
    assert overflow == []
    inset = layout_inset_px(region, margin)
    assert inset >= 3
    interior = interior_mask(np.array(image), region)
    allowed = inset_layout_mask(interior, inset)
    changed = np.any(np.array(result) != np.array(image), axis=2)
    assert int(changed.sum()) > 20
    assert not np.any(changed & (allowed == 0))


def test_stroke_and_margin_pick_a_smaller_size():
    phrase = "Длинная реплика которая занимает почти весь баллон целиком"
    image, plain = _speech_bubble(phrase)
    _image, stroked = _speech_bubble(phrase)
    _image, margined = _speech_bubble(phrase)
    base = Typesetter(min_font_size=10, max_font_size=64, lang="ru")
    with_stroke = Typesetter(min_font_size=10, max_font_size=64, lang="ru", stroke_ratio=0.2)
    with_margin = Typesetter(min_font_size=10, max_font_size=64, lang="ru", margin_ratio=0.12)
    base.render(image, [plain])
    with_stroke.render(image, [stroked])
    with_margin.render(image, [margined])
    assert plain.style.font_size > stroked.style.font_size
    assert plain.style.font_size > margined.style.font_size


def test_zero_margin_does_not_shrink_the_bubble():
    from src.components.typesetter import layout_inset_px

    phrase = "Короткая"
    image, region = _speech_bubble(phrase)
    other_image, other = _speech_bubble(phrase)
    Typesetter(min_font_size=12, max_font_size=40, lang="ru", margin_ratio=0, stroke_ratio=0).render(
        image, [region]
    )
    Typesetter(min_font_size=12, max_font_size=40, lang="ru").render(other_image, [other])
    assert region.style.font_size == other.style.font_size
    assert layout_inset_px(region, 0) == 0
    narration = TextRegion(
        id=2,
        bbox=(0, 0, 100, 40),
        translation="Текст",
        block_type="narration",
    )
    sfx = TextRegion(id=3, bbox=(0, 0, 80, 40), bubble_bbox=(0, 0, 80, 40), block_type="sfx")
    assert layout_inset_px(narration, 0.08) == 0
    assert layout_inset_px(sfx, 0.08) == 0


def test_sfx_long_text_shrinks_instead_of_overflow():
    image = Image.new("RGB", (180, 56), "white")
    region = TextRegion(
        id=4,
        bbox=(8, 8, 164, 40),
        translation="БАБАХГРОХОТ",
        block_type="sfx",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    _result, overflow = Typesetter(min_font_size=10, max_font_size=48, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    assert region.overflow is False
    assert 10 <= region.style.font_size < 48


def test_black_bubble_is_drawn_in_white():
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 170, 110), fill="black")
    region = TextRegion(
        id=1,
        bbox=(50, 45, 80, 30),
        bubble_bbox=(10, 10, 160, 100),
        translation="Да",
        block_type="dialogue",
        style=TextStyle(fill_rgb=(0, 0, 0)),
    )
    result, overflow = Typesetter(min_font_size=16, max_font_size=28, lang="ru").render(image, [region])
    assert overflow == []
    light = np.all(np.array(result) > 200, axis=2)
    assert int(light.sum()) > 10
    assert region.style.fill_rgb == (255, 255, 255)


def test_readable_red_on_white_stays_red():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(220, 20, 20), alignment="left"),
    )
    result, overflow = Typesetter(min_font_size=18, max_font_size=18, lang="ru").render(image, [region])
    assert overflow == []
    assert region.style.fill_rgb == (220, 20, 20)
    red = np.array(result)
    assert int(np.sum((red[:, :, 0] > 150) & (red[:, :, 1] < 80))) > 10


def test_override_below_minimum_draws_at_minimum():
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=5,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=5),
    )
    _result, overflow = Typesetter(min_font_size=10, max_font_size=40, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    assert region.style.font_size == 10


def test_steep_sfx_stays_inside_its_box():
    """Вертикальный звук с поворотом 72° не закрашивает баллон сверху."""
    image = Image.new("RGB", (400, 500), "white")
    region = TextRegion(
        id=11,
        bbox=(160, 250, 80, 180),
        translation="СЖАТЬ",
        block_type="sfx",
        style=TextStyle(
            fill_rgb=(0, 0, 0),
            font_size_override=28,
            rotation=72,
            stroke_mode="none",
            warp={"kind": "arc", "bend": 0.34, "quad": None, "mesh": None},
        ),
    )
    result, overflow = Typesetter(min_font_size=10, max_font_size=40, lang="ru").render(
        image, [region],
    )
    assert overflow == []
    ink = np.any(np.array(result) < 40, axis=2)
    ys, xs = np.nonzero(ink)
    assert len(xs) > 10
    x, y, w, h = region.bbox
    assert x <= float(xs.mean()) <= x + w
    assert y <= float(ys.mean()) <= y + h
    assert not np.any(ink[: y])
