"""Стиль блока: старый словарь, новые поля, слой вёрстки."""

from pathlib import Path

import numpy as np
from PIL import Image

from src.components import typesetter as typesetter_module
from src.components.typesetter import Typesetter
from src.models import TextRegion, TextStyle

_OLD_KEYS = {
    "fill_rgb": [0, 0, 0],
    "stroke_rgb": None,
    "font_size": 16,
    "alignment": "center",
    "uppercase": False,
    "line_height": 18,
    "font_size_override": 0,
}

_HISTORICAL = {
    "font_id": "",
    "stroke_mode": "auto",
    "stroke_width": 0.0,
    "letter_spacing": 0.0,
    "line_spacing": 0.0,
    "rotation": 0.0,
    "skew_x": 0.0,
    "warp": {"kind": "none", "bend": 0.0, "quad": None, "mesh": None},
}


def test_old_payload_roundtrip_keeps_historical_defaults():
    """Словарь только со старыми ключами даёт прежние значения по умолчанию."""
    style = TextStyle.from_dict(dict(_OLD_KEYS))
    assert style == TextStyle()
    restored = TextStyle.from_dict(style.to_dict())
    assert restored == style
    dumped = style.to_dict()
    for key, value in _OLD_KEYS.items():
        assert dumped[key] == value
    for key, value in _HISTORICAL.items():
        assert dumped[key] == value


def test_new_fields_roundtrip_and_clamp_colors():
    mesh = [[[float(col), float(row)] for col in range(4)] for row in range(4)]
    payload = {
        "fill_rgb": [300, -5, 10],
        "stroke_rgb": [256, 128, -1],
        "font_size": 20,
        "alignment": "left",
        "uppercase": True,
        "line_height": 22,
        "font_size_override": 18,
        "font_id": "PT_Sans-Web-Regular",
        "stroke_mode": "custom",
        "stroke_width": 2.2,
        "letter_spacing": 1.5,
        "line_spacing": 3.0,
        "rotation": 12.0,
        "skew_x": -4.0,
        "warp": {
            "kind": "arc",
            "bend": 0.25,
            "quad": [[0, 0], [10, 1], [9, 12], [1, 11]],
            "mesh": mesh,
        },
    }
    style = TextStyle.from_dict(payload)
    assert style.fill_rgb == (255, 0, 10)
    assert style.stroke_rgb == (255, 128, 0)
    assert style.font_id == "PT_Sans-Web-Regular"
    assert style.stroke_mode == "custom"
    assert style.stroke_width == 2.2
    assert style.letter_spacing == 1.5
    assert style.line_spacing == 3.0
    assert style.rotation == 12.0
    assert style.skew_x == -4.0
    assert style.warp["kind"] == "arc"
    assert style.warp["bend"] == 0.25
    assert len(style.warp["mesh"]) == 16
    assert TextStyle.from_dict(style.to_dict()) == style


def test_bad_warp_kind_and_stroke_mode_fall_back():
    style = TextStyle.from_dict({
        "stroke_mode": "glow",
        "warp": {"kind": "twist", "bend": 0.4, "quad": None, "mesh": None},
    })
    assert style.stroke_mode == "auto"
    assert style.warp["kind"] == "none"
    assert style.warp["bend"] == 0.4


def _page_region(style: TextStyle) -> TextRegion:
    return TextRegion(
        id=1,
        bbox=(8, 8, 224, 124),
        translation="Привет",
        block_type="narration",
        style=style,
    )


def test_neutral_style_skips_warp_and_matches_explicit_defaults(monkeypatch):
    """Нулевые поля не зовут варп и не меняют быстрый путь."""
    calls = {"n": 0}
    real = typesetter_module.warp_image

    def spy(rgba, kind, bend=0.0, quad=None, mesh=None):
        calls["n"] += 1
        return real(rgba, kind, bend=bend, quad=quad, mesh=mesh)

    monkeypatch.setattr(typesetter_module, "warp_image", spy)
    image = Image.new("RGB", (240, 140), "white")
    setter = Typesetter(min_font_size=12, max_font_size=28, lang="ru")
    plain = TextStyle(fill_rgb=(0, 0, 0), alignment="center", font_size_override=20)
    explicit = TextStyle(
        fill_rgb=(0, 0, 0),
        alignment="center",
        font_size_override=20,
        rotation=0,
        skew_x=0,
        letter_spacing=0,
        line_spacing=0,
        warp={"kind": "none", "bend": 0, "quad": None, "mesh": None},
    )
    first, overflow_a = setter.render(image, [_page_region(plain)])
    second, overflow_b = setter.render(image, [_page_region(explicit)])
    assert overflow_a == []
    assert overflow_b == []
    assert calls["n"] == 0
    assert np.array_equal(np.array(first), np.array(second))


def test_layer_path_draws_rotation_skew_spacing_and_arc():
    image = Image.new("RGB", (240, 140), "white")
    setter = Typesetter(min_font_size=12, max_font_size=28, lang="ru")
    styles = [
        TextStyle(fill_rgb=(0, 0, 0), alignment="center", rotation=12, font_size_override=20),
        TextStyle(fill_rgb=(0, 0, 0), alignment="center", skew_x=18, font_size_override=20),
        TextStyle(
            fill_rgb=(0, 0, 0),
            alignment="center",
            letter_spacing=1.5,
            line_spacing=2,
            font_size_override=20,
        ),
        TextStyle(
            fill_rgb=(0, 0, 0),
            alignment="center",
            font_size_override=20,
            warp={"kind": "arc", "bend": 0.12, "quad": None, "mesh": None},
        ),
        TextStyle(
            fill_rgb=(0, 0, 0),
            alignment="center",
            font_size_override=20,
            stroke_mode="custom",
            stroke_rgb=(255, 0, 0),
            stroke_width=0,
        ),
        TextStyle(
            fill_rgb=(0, 0, 0),
            alignment="center",
            font_size_override=20,
            stroke_mode="none",
        ),
    ]
    for style in styles:
        result, overflow = setter.render(image, [_page_region(style)])
        assert result.size == image.size
        assert overflow == []
        dark = int(np.sum(np.any(np.array(result) < 40, axis=2)))
        assert dark > 10


def test_rotated_layer_stays_on_block_center():
    image = Image.new("RGB", (400, 400), "white")
    region = TextRegion(
        id=1,
        bbox=(140, 140, 120, 120),
        translation="СЖАТЬ",
        block_type="sfx",
        style=TextStyle(
            fill_rgb=(0, 0, 0),
            alignment="center",
            font_size_override=28,
            rotation=72,
            stroke_mode="none",
        ),
    )
    result, overflow = Typesetter(min_font_size=12, max_font_size=40, lang="ru").render(
        image, [region]
    )
    assert overflow == []
    ink = np.any(np.array(result) < 40, axis=2)
    ys, xs = np.nonzero(ink)
    assert len(xs) > 10
    assert abs(float(xs.mean()) - 200) < 24
    assert abs(float(ys.mean()) - 200) < 24


def test_arc_calls_warp_fast_stroke_does_not(monkeypatch):
    calls = []
    real = typesetter_module.warp_image

    def spy(rgba, kind, bend=0.0, quad=None, mesh=None):
        calls.append(kind)
        return real(rgba, kind, bend=bend, quad=quad, mesh=mesh)

    monkeypatch.setattr(typesetter_module, "warp_image", spy)
    image = Image.new("RGB", (240, 140), "white")
    setter = Typesetter(min_font_size=12, max_font_size=28, lang="ru")
    setter.render(image, [_page_region(TextStyle(
        fill_rgb=(0, 0, 0),
        alignment="center",
        font_size_override=20,
        stroke_mode="none",
    ))])
    assert calls == []
    setter.render(image, [_page_region(TextStyle(
        fill_rgb=(0, 0, 0),
        alignment="center",
        font_size_override=20,
        warp={"kind": "wave", "bend": 0.1, "quad": None, "mesh": None},
    ))])
    assert calls == ["wave"]


def test_font_id_resolves_through_catalog(monkeypatch, tmp_path):
    target = tmp_path / "marked.ttf"
    target.write_bytes(b"x")
    recorded = []
    real_load = typesetter_module._load_font

    def spy(path, size):
        recorded.append(Path(path) if path is not None else None)
        return real_load(None, size)

    monkeypatch.setattr(typesetter_module, "_load_font", spy)
    monkeypatch.setattr(
        typesetter_module,
        "scan_fonts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        typesetter_module,
        "resolve_font_path",
        lambda font_id, faces=None: target if font_id == "marked" else None,
    )
    image = Image.new("RGB", (240, 140), "white")
    region = _page_region(TextStyle(
        fill_rgb=(0, 0, 0),
        alignment="center",
        font_size_override=18,
        font_id="marked",
    ))
    Typesetter(min_font_size=12, max_font_size=28, lang="ru").render(image, [region])
    assert target in recorded


def test_user_fonts_dir_is_passed_to_catalog(monkeypatch, tmp_path):
    """Каталог пользователя доходит до scan_fonts, страница его не сканирует сама."""
    seen = {}

    def spy(models_fonts=None, user_dir=None, system_dirs=None, include_system=True):
        seen["user_dir"] = user_dir
        return []

    monkeypatch.setattr(typesetter_module, "scan_fonts", spy)
    monkeypatch.setattr(typesetter_module, "resolve_font_path", lambda font_id, faces=None: None)
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=18, font_id="missing"),
    )
    Typesetter(min_font_size=12, max_font_size=28, lang="ru", user_fonts=tmp_path).render(image, [region])
    assert seen["user_dir"] == tmp_path


def test_empty_font_id_skips_catalog(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("каталог не нужен при пустом font_id")

    monkeypatch.setattr(typesetter_module, "scan_fonts", fail)
    monkeypatch.setattr(typesetter_module, "resolve_font_path", fail)
    image = Image.new("RGB", (220, 80), "white")
    region = TextRegion(
        id=1,
        bbox=(10, 10, 200, 60),
        translation="Привет",
        block_type="narration",
        style=TextStyle(fill_rgb=(0, 0, 0), alignment="left", font_size_override=18),
    )
    result, overflow = Typesetter(min_font_size=12, max_font_size=28, lang="ru").render(
        image, [region]
    )
    assert overflow == []
    assert result.size == image.size
