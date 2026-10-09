"""Эвристика RapidOCR._guess_type: баллон, вывеска, shout."""

from src.components.rapid_ocr import RapidOcr
from src.models import TextRegion, should_translate


def _region(text: str, bubble: bool = False) -> TextRegion:
    bbox = (0, 0, 40, 20)
    return TextRegion(
        id=1,
        bbox=bbox,
        text=text,
        bubble_bbox=bbox if bubble else None,
    )


def test_balloon_caps_is_dialogue_not_sfx():
    region = _region("HELP", bubble=True)
    RapidOcr._guess_type(region)
    assert region.block_type == "dialogue"
    assert should_translate(region) is True


def test_free_shout_is_sfx_and_skipped_by_default():
    region = _region("BOOM", bubble=False)
    RapidOcr._guess_type(region)
    assert region.block_type == "sfx"
    assert should_translate(region) is False
    assert should_translate(region, translate_sfx=True) is True


def test_short_free_label_is_sign_and_skipped():
    region = _region("Sale", bubble=False)
    RapidOcr._guess_type(region)
    assert region.block_type == "sign"
    assert should_translate(region) is False


def test_long_free_caption_is_narration():
    region = _region(
        "Meanwhile in the distant city the story continues without pause",
        bubble=False,
    )
    RapidOcr._guess_type(region)
    assert region.block_type == "narration"
    assert should_translate(region) is True
