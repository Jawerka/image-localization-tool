"""Каталог шрифтов и контракт докачки OFL. Сеть не используется."""

import inspect
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from src.app.model_manager import FONT_PACK, _DOWNLOADS, download, download_font_pack, status
from src.components.font_catalog import (
    FONT_ROLE_DIALOGUE,
    FONT_ROLE_HANDWRITTEN,
    FONT_ROLE_PIXEL,
    FONT_ROLE_SFX,
    FONT_ROLE_SFX_COMEDY,
    FONT_ROLE_SFX_TECH,
    FONT_ROLE_SHOUT,
    FONT_ROLE_STENCIL,
    FONT_ROLE_TITLE,
    assign_stylized_fonts,
    categorize,
    find_font,
    has_cyrillic,
    resolve_font_path,
    role_font_id,
    scan_fonts,
)
from src.models import TextRegion


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
    assert categorize("First Time Writing") == "handwritten"
    assert categorize("", "FirstTimeWriting.ttf") == "handwritten"
    assert categorize("Liber Struct") == "sfx"
    assert categorize("", "Liber-Struct.ttf") == "sfx"
    assert categorize("Blaec") == "shout"
    assert categorize("", "Blaec-Regular.ttf") == "shout"
    assert categorize("", "PublicPixel.ttf") == "sfx"
    assert categorize("Public Pixel") == "sfx"
    assert categorize("", "Pixelzone.ttf") == "sfx"
    assert categorize("", "DeltaBlock-Regular.ttf") == "sfx"
    assert categorize("Unsightly") == "sfx"
    assert categorize("", "OperationNapalm-Regular.ttf") == "shout"
    assert categorize("", "VyazPixel.ttf") == "handwritten"


def test_role_font_id_matches_docs_plan():
    assert role_font_id(TextRegion(id=1, bbox=(0, 0, 1, 1), text="BANG", block_type="sfx")) == FONT_ROLE_SFX
    assert role_font_id(TextRegion(id=2, bbox=(0, 0, 1, 1), text="хаха", block_type="sfx")) == FONT_ROLE_SFX_COMEDY
    assert role_font_id(TextRegion(id=3, bbox=(0, 0, 1, 1), text="R2D2", block_type="sfx")) == FONT_ROLE_SFX_TECH
    assert (
        role_font_id(
            TextRegion(
                id=4, bbox=(0, 0, 1, 1), text="hi", block_type="dialogue", bubble_bbox=(0, 0, 1, 1)
            )
        )
        == FONT_ROLE_DIALOGUE
    )
    assert role_font_id(TextRegion(id=5, bbox=(0, 0, 1, 1), text="TITLE", block_type="title")) == FONT_ROLE_TITLE
    assert role_font_id(TextRegion(id=6, bbox=(0, 0, 1, 1), text="DANGER", block_type="sign")) == FONT_ROLE_STENCIL
    assert role_font_id(TextRegion(id=7, bbox=(0, 0, 1, 1), text="note", block_type="sign")) == FONT_ROLE_HANDWRITTEN
    assert role_font_id(TextRegion(id=8, bbox=(0, 0, 1, 1), text="beep", block_type="noise")) == FONT_ROLE_PIXEL
    assert role_font_id(TextRegion(id=9, bbox=(0, 0, 1, 1), text="CRASH", block_type="sign")) == FONT_ROLE_STENCIL
    assert role_font_id(TextRegion(id=10, bbox=(0, 0, 1, 1), text="hello", block_type="sign")) == FONT_ROLE_HANDWRITTEN


def test_assign_stylized_fonts_trial_and_kill_switch(tmp_path):
    for name, family in (
        (FONT_ROLE_SFX, "Liber Struct"),
        (FONT_ROLE_HANDWRITTEN, "First Time Writing"),
        (FONT_ROLE_TITLE, "Jupiteroid Light"),
        (FONT_ROLE_SHOUT, "Operation Napalm"),
        (FONT_ROLE_DIALOGUE, "Heroika"),
    ):
        _make_font(tmp_path / f"{name}.ttf", range(0x0410, 0x0450), family)
    faces = scan_fonts(models_fonts=tmp_path, include_system=False)

    sfx = TextRegion(id=1, bbox=(0, 0, 10, 10), text="BANG", block_type="sfx")
    laugh = TextRegion(id=2, bbox=(0, 0, 10, 10), text="haha", block_type="sfx")
    free = TextRegion(id=3, bbox=(0, 0, 10, 10), text="hello", block_type="sign")
    caps = TextRegion(id=4, bbox=(0, 0, 10, 10), text="CRASH", block_type="sign")
    bubble = TextRegion(
        id=5, bbox=(0, 0, 10, 10), text="hi", block_type="dialogue", bubble_bbox=(0, 0, 10, 10)
    )
    locked = TextRegion(id=6, bbox=(0, 0, 10, 10), text="X", block_type="sfx")
    locked.style.font_id = "Custom"
    edited = TextRegion(id=7, bbox=(0, 0, 10, 10), text="Y", block_type="sfx", edited=True)
    title = TextRegion(id=8, bbox=(0, 0, 10, 10), text="Chapter", block_type="title")

    assign_stylized_fonts([sfx, laugh, free, caps, bubble, locked, edited, title], faces=faces)
    assert sfx.style.font_id == FONT_ROLE_SFX
    assert laugh.style.font_id == FONT_ROLE_SFX_COMEDY
    assert free.style.font_id == FONT_ROLE_HANDWRITTEN
    assert caps.style.font_id == FONT_ROLE_STENCIL
    assert bubble.style.font_id == FONT_ROLE_DIALOGUE
    assert title.style.font_id == FONT_ROLE_TITLE
    assert locked.style.font_id == "Custom"
    assert edited.style.font_id == ""

    plain = TextRegion(id=9, bbox=(0, 0, 10, 10), text="Z", block_type="sfx")
    assign_stylized_fonts([plain], enabled=False, faces=faces)
    assert plain.style.font_id == ""


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
