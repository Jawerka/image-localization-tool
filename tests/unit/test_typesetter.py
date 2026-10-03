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
