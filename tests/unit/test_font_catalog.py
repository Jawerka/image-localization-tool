"""Каталог шрифтов и контракт докачки OFL. Сеть не используется."""

import inspect
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from src.app.model_manager import FONT_PACK, _DOWNLOADS, download, download_font_pack, status
from src.components.font_catalog import (
    categorize,
    find_font,
    has_cyrillic,
    resolve_font_path,
    scan_fonts,
)


def _make_font(path, codepoints, family="Test Sans") -> None:
    ordered = sorted(codepoints)
    glyphs = [".notdef"] + [f"g{codepoint:04X}" for codepoint in ordered]
    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder(glyphs)
    builder.setupCharacterMap({codepoint: f"g{codepoint:04X}" for codepoint in ordered})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.lineTo((100, 100))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({name: glyph for name in glyphs})
    builder.setupHorizontalMetrics({name: (500, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(path)


def test_has_cyrillic_requires_full_block(tmp_path):
    full = tmp_path / "full.ttf"
    latin = tmp_path / "latin.ttf"
    partial = tmp_path / "partial.ttf"
    _make_font(full, range(0x0410, 0x0450), "Test Sans")
    _make_font(latin, [0x0041], "Test Sans")
    _make_font(partial, range(0x0410, 0x044F), "Test Sans")

    assert has_cyrillic(full) is True
    assert has_cyrillic(latin) is False
    assert has_cyrillic(partial) is False
    assert has_cyrillic(tmp_path / "missing.ttf") is False
    (tmp_path / "broken.ttf").write_bytes(b"not-a-font")
    assert has_cyrillic(tmp_path / "broken.ttf") is False


def test_categorize_known_families():
    assert categorize("Russo One") == "shout"
    assert categorize("Caveat") == "handwritten"
    assert categorize("Creepster") == "sfx"
    assert categorize("PT Sans") == "dialogue"
    assert categorize("Marck Script") == "handwritten"
    assert categorize("", "Bangers-Regular.ttf") == "shout"
    assert categorize("Special Elite") == "sfx"
    assert categorize("Caveat Impact") == "handwritten"
    assert categorize("Creepster Black") == "sfx"
    assert categorize("pt sans", "PT_Sans-Web-Regular.ttf") == "dialogue"


def test_scan_fonts_categories_and_cyrillic(tmp_path):
    _make_font(tmp_path / "PT_Sans.ttf", range(0x0410, 0x0450), "PT Sans")
    _make_font(tmp_path / "Oswald-Regular.otf", range(0x0410, 0x0450), "Oswald")
    _make_font(tmp_path / "Caveat.ttf", range(0x0410, 0x0450), "Caveat")
    _make_font(tmp_path / "Creepster.ttf", [0x0041], "Creepster")
    (tmp_path / "notes.txt").write_text("skip", encoding="utf-8")

    faces = scan_fonts(models_fonts=tmp_path, user_dir=None, include_system=False)
    by_id = {face.id: face for face in faces}

    assert [face.id for face in faces] == sorted(by_id)
    assert set(by_id) == {"PT_Sans", "Oswald-Regular", "Caveat", "Creepster"}
    assert by_id["PT_Sans"].category == "dialogue"
    assert by_id["PT_Sans"].cyrillic is True
    assert by_id["PT_Sans"].family == "PT Sans"
    assert by_id["Oswald-Regular"].category == "shout"
    assert by_id["Oswald-Regular"].cyrillic is True
    assert by_id["Caveat"].category == "handwritten"
    assert by_id["Caveat"].cyrillic is True
    assert by_id["Creepster"].category == "sfx"
    assert by_id["Creepster"].cyrillic is False
    assert by_id["PT_Sans"].path.endswith("PT_Sans.ttf")


def test_find_font_and_resolve_path(tmp_path, monkeypatch):
    _make_font(tmp_path / "Caveat.ttf", range(0x0410, 0x0450), "Caveat")
    faces = scan_fonts(models_fonts=tmp_path, include_system=False)
    found = find_font("Caveat", faces)

    assert found is not None
    assert found.category == "handwritten"
    resolved = resolve_font_path("Caveat", faces)
    assert resolved is not None
    assert resolved == Path(found.path)
    assert resolved.is_file()
    assert find_font("missing", faces) is None
    assert resolve_font_path("missing", faces) is None
    assert find_font("", faces) is None

    monkeypatch.setattr("src.components.font_catalog.scan_fonts", lambda **_kwargs: faces)
    assert find_font("Caveat") == found
    assert resolve_font_path("Caveat") == resolved


def test_empty_font_id_does_not_scan(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("scan")

    monkeypatch.setattr("src.components.font_catalog.scan_fonts", boom)
    assert find_font("") is None
    assert resolve_font_path("") is None


def test_duplicate_stem_prefixes_source(tmp_path):
    models = tmp_path / "models"
    user = tmp_path / "user"
    models.mkdir()
    user.mkdir()
    _make_font(models / "Shared.ttf", [0x0041], "Shared Models")
    _make_font(user / "Shared.ttf", [0x0041], "Shared User")

    faces = scan_fonts(models_fonts=models, user_dir=user, include_system=False)
    by_id = {face.id: face for face in faces}

    assert [face.id for face in faces] == ["Shared", "user-Shared"]
    assert by_id["Shared"].family == "Shared Models"
    assert by_id["user-Shared"].family == "Shared User"


def test_corrupt_font_and_missing_dirs(tmp_path):
    _make_font(tmp_path / "PTSans.ttf", range(0x0410, 0x0450), "PT Sans")
    (tmp_path / "Broken.ttf").write_bytes(b"not-a-font")

    faces = scan_fonts(models_fonts=tmp_path, include_system=False)
    by_id = {face.id: face for face in faces}
    assert set(by_id) == {"PTSans", "Broken"}
    assert by_id["Broken"].family == "Broken"
    assert by_id["Broken"].cyrillic is False
    assert by_id["Broken"].category == "dialogue"
    assert by_id["PTSans"].cyrillic is True

    empty = scan_fonts(
        models_fonts=tmp_path / "absent",
        user_dir=tmp_path / "also-absent",
        system_dirs=[tmp_path / "no-system"],
        include_system=True,
    )
    assert empty == []


def test_default_system_dir_uses_windir(monkeypatch, tmp_path):
    windir = tmp_path / "Win"
    fonts = windir / "Fonts"
    fonts.mkdir(parents=True)
    _make_font(fonts / "Segoe.ttf", [0x0041], "Segoe UI")
    monkeypatch.setenv("WINDIR", str(windir))

    faces = scan_fonts(models_fonts=tmp_path / "no-models", include_system=True)
    assert [face.id for face in faces] == ["Segoe"]
    assert faces[0].category == "dialogue"


def test_font_pack_contract_without_network():
    """download('font_pack') здесь не вызывается."""
    assert callable(download_font_pack)
    assert set(_DOWNLOADS) == {"lama", "font", "detector"}
    assert "font_pack" not in _DOWNLOADS
    assert 'kind == "font_pack"' in inspect.getsource(download)

    names = [filename for _url, filename in FONT_PACK]
    assert names == [
        "PT_Sans-Web-Regular.ttf",
        "RussoOne-Regular.ttf",
        "MarckScript-Regular.ttf",
        "Creepster-Regular.ttf",
    ]
    for url, filename in FONT_PACK:
        assert url.startswith("https://raw.githubusercontent.com/google/fonts/main/ofl/")
        assert url.endswith("/" + filename)
        assert "[" not in filename
        assert filename.endswith(".ttf")

    report = status()
    assert set(report) == {"detector", "lama", "font"}


def test_unknown_download_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        download("not-a-kind", tmp_path)
