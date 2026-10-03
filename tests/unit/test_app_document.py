"""Сравнение документов страницы."""

from src.app.document import PageDocument, diff_plan
from src.models import MaskStroke, TextRegion, TextStyle


def _region(**kwargs) -> TextRegion:
    values = dict(
        id=1,
        bbox=(10, 20, 30, 40),
        text="Hi",
        translation="Привет",
        block_type="dialogue",
        speaker="",
    )
    values.update(kwargs)
    return TextRegion(**values)


def _doc(*regions, strokes=None, version=1) -> PageDocument:
    return PageDocument(version=version, regions=list(regions), strokes=list(strokes or []))


def _clone(document: PageDocument) -> PageDocument:
    return PageDocument.from_dict(document.to_dict())


def test_old_regions_json_without_version():
    document = PageDocument.from_dict({
        "source_path": "page.png",
        "reading_direction": "rtl",
        "regions": [{"id": 3, "bbox": [1, 2, 3, 4], "text": "Yo"}],
    })
    assert document.version == 1
    assert document.strokes == []
    assert document.reading_direction == "rtl"
    assert document.regions[0].text == "Yo"
    assert document.regions[0].skip is False
    assert document.regions[0].style.font_size_override == 0


def test_diff_plan_none_typeset_and_clean():
    original = _doc(_region())
    same = _clone(original)
    same.version = 9
    same.regions[0].edited = True
    same.regions[0].manual = True
    same.regions[0].overflow = True
    assert diff_plan(original, same) == "none"

    translated = _clone(original)
    translated.regions[0].translation = "Здравствуй"
    assert diff_plan(original, translated) == "typeset"

    shouted = _clone(original)
    shouted.regions[0].style = TextStyle(uppercase=True)
    assert diff_plan(original, shouted) == "typeset"

    sized = _clone(original)
    sized.regions[0].style.font_size_override = 24
    assert diff_plan(original, sized) == "typeset"

    spoken = _clone(original)
    spoken.regions[0].speaker = "Аня"
    assert diff_plan(original, spoken) == "typeset"

    moved = _clone(original)
    moved.regions[0].bbox = (1, 2, 3, 4)
    assert diff_plan(original, moved) == "clean"

    skipped = _clone(original)
    skipped.regions[0].skip = True
    assert diff_plan(original, skipped) == "clean"

    retyped = _clone(original)
    retyped.regions[0].block_type = "sfx"
    assert diff_plan(original, retyped) == "clean"

    reworded = _clone(original)
    reworded.regions[0].text = "Hello"
    assert diff_plan(original, reworded) == "clean"

    added = _doc(_region(), _region(id=2, bbox=(50, 60, 10, 10)))
    assert diff_plan(original, added) == "clean"


def test_diff_plan_strokes():
    original = _doc(_region(), strokes=[MaskStroke(mode="erase", radius=4, points=[(1, 2)])])
    same = _clone(original)
    assert diff_plan(original, same) == "none"

    changed = _clone(original)
    changed.strokes[0].points = [(1, 2), (3, 4)]
    assert diff_plan(original, changed) == "clean"

    cleared = _doc(_region())
    assert diff_plan(original, cleared) == "clean"
