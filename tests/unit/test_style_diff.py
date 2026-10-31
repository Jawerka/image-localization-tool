"""Смена только стиля региона по-прежнему просит вёрстку, не очистку."""

from src.app.document import PageDocument, diff_plan
from src.models import TextRegion, TextStyle


def _document() -> PageDocument:
    region = TextRegion(
        id=1,
        bbox=(10, 20, 30, 40),
        text="Hi",
        translation="Привет",
        block_type="dialogue",
        style=TextStyle(),
    )
    return PageDocument(regions=[region])


def test_unchanged_style_roundtrip_is_none():
    original = _document()
    same = PageDocument.from_dict(original.to_dict())
    assert diff_plan(original, same) == "none"


def test_style_only_changes_request_typeset():
    original = _document()
    updated = []

    spaced = PageDocument.from_dict(original.to_dict())
    spaced.regions[0].style.letter_spacing = 1.25
    updated.append(spaced)

    leading = PageDocument.from_dict(original.to_dict())
    leading.regions[0].style.line_spacing = 4
    updated.append(leading)

    rotated = PageDocument.from_dict(original.to_dict())
    rotated.regions[0].style.rotation = 8
    updated.append(rotated)

    skewed = PageDocument.from_dict(original.to_dict())
    skewed.regions[0].style.skew_x = -6
    updated.append(skewed)

    stroked = PageDocument.from_dict(original.to_dict())
    stroked.regions[0].style.stroke_mode = "none"
    updated.append(stroked)

    faced = PageDocument.from_dict(original.to_dict())
    faced.regions[0].style.font_id = "PT_Sans-Web-Regular"
    updated.append(faced)

    warped = PageDocument.from_dict(original.to_dict())
    warped.regions[0].style.warp = {
        "kind": "wave",
        "bend": 0.2,
        "quad": None,
        "mesh": None,
    }
    updated.append(warped)

    for document in updated:
        assert diff_plan(original, document) == "typeset"
