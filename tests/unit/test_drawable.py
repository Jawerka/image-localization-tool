"""Отбор регионов для вёрстки: ручной перевод рисуется даже без OCR."""

from src.app.worker import _drawable
from src.models import TextRegion


def _region(**kwargs):
    data = {
        "id": 1,
        "bbox": (0, 0, 40, 20),
        "text": "",
        "translation": "",
        "skip": False,
        "block_type": "noise",
    }
    data.update(kwargs)
    return TextRegion(**data)


def test_drawable_includes_manual_translation_without_ocr():
    region = _region(translation="Привет", text="")
    assert _drawable([region]) == [region]


def test_drawable_skips_when_skip_flag():
    region = _region(translation="Привет", skip=True)
    assert _drawable([region]) == []


def test_drawable_skips_empty_translation():
    region = _region(text="Hello", translation="  ")
    assert _drawable([region]) == []


def test_drawable_includes_sfx_when_user_typed_translation():
    region = _region(text="BOOM", translation="БАМ", block_type="sfx")
    assert _drawable([region], translate_sfx=False) == [region]
