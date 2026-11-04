"""Толстая автообводка на небелом фоне и одинаковый запас вёрстки/рисования."""

import copy

import numpy as np
from PIL import Image
import pytest

from src.components.typesetter import Typesetter
from src.models import TextRegion, TextStyle


@pytest.mark.parametrize('color', [(0, 0, 0), (120, 120, 120), (170, 190, 230), (252, 235, 180)])
def test_uniform_nonwhite_background_gets_thicker_outline(color):
    region = TextRegion(1, (20, 20, 180, 70), translation='Привет')
    setter = Typesetter(stroke_ratio=.08)
    mask = np.full((110, 220), 255, np.uint8)
    white = np.full((110, 220, 3), 255, np.uint8)
    image = np.full_like(white, color)
    _, normal = setter._stroke_paint(white, mask, region, 28)
    stroke, thick = setter._stroke_paint(image, mask, region, 28)
    assert stroke == (255, 255, 255)
    assert thick > normal


def test_near_white_and_sparse_noise_do_not_increase_outline():
    region = TextRegion(1, (20, 20, 180, 70), translation='Привет')
    setter = Typesetter(stroke_ratio=.08)
    mask = np.full((110, 220), 255, np.uint8)
    white = np.full((110, 220, 3), 255, np.uint8)
    noisy = np.full_like(white, (252, 250, 248))
    noisy[::20] = 220
    assert setter._stroke_paint(noisy, mask, region, 28) == setter._stroke_paint(white, mask, region, 28)


@pytest.mark.parametrize('mode,width', [('none', 0), ('custom', 3)])
def test_manual_outline_is_not_increased(mode, width):
    region = TextRegion(1, (20, 20, 180, 70), translation='Привет',
                        style=TextStyle(stroke_mode=mode, stroke_width=3, stroke_rgb=(200, 10, 20)))
    image = np.zeros((110, 220, 3), np.uint8)
    stroke, actual = Typesetter()._stroke_paint(image, np.full((110, 220), 255, np.uint8), region, 28)
    assert actual == width
    assert stroke == ((200, 10, 20) if mode == 'custom' else None)


def test_bubble_reserves_same_thick_outline_as_final_paint(monkeypatch):
    from src.components import adaptive_text
    original = adaptive_text.fit_balloon_shape
    reserved = {}
    def fit(*args, **kwargs):
        callback = kwargs['stroke_pad']
        def record(size):
            reserved[size] = callback(size)
            return reserved[size]
        kwargs['stroke_pad'] = record
        return original(*args, **kwargs)
    monkeypatch.setattr(adaptive_text, 'fit_balloon_shape', fit)
    region = TextRegion(1, (25, 25, 180, 80), translation='Привет, мир!', bubble_bbox=(10, 10, 220, 120),
                        auto_layout={'version': 1, 'kind': 'bubble'})
    image = Image.new('RGB', (240, 140), (70, 80, 100))
    setter = Typesetter(stroke_ratio=.08)
    _, overflow = setter.render(image, [region])
    assert not overflow
    chosen = setter._last_layouts[1]['font_size']
    mask = np.full((140, 240), 255, np.uint8)
    _, actual = setter._stroke_paint(np.asarray(image), mask, region, chosen)
    assert reserved[chosen] == actual


def test_free_outline_does_not_accumulate_or_change_manual_style():
    geometry = {'version': 1, 'kind': 'free', 'outline_px': 3,
                'ink_bbox': [20, 20, 180, 65], 'source_bbox': [20, 20, 180, 65]}
    region = TextRegion(1, (20, 20, 180, 65), text='HELLO', translation='ПРИВЕТ', block_type='sfx',
                        auto_layout=copy.deepcopy(geometry))
    setter = Typesetter()
    image = Image.new('RGB', (230, 110), (80, 120, 150))
    first, _ = setter.render(image, [region])
    second, _ = setter.render(image, [region])
    assert np.array_equal(np.asarray(first), np.asarray(second))
    assert region.auto_layout == geometry
    assert region.style.stroke_mode == 'auto'
    assert region.style.stroke_width == 0
