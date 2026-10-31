"""Эвристика RapidOCR._guess_type и порядок слов на странице."""

from PIL import Image

from src.components.rapid_ocr import OcrWord, RapidOcr, _reading_lines
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


def _join(words, direction="ltr") -> str:
    return " ".join(word.text for word in _reading_lines(words, direction))


def test_reading_order_groups_superscript_and_columns():
    words = [
        OcrWord("WORD", (10, 20, 40, 20), 0.9),
        OcrWord("TM", (52, 16, 12, 10), 0.9),
        OcrWord("LEFT", (10, 60, 30, 12), 0.9),
        OcrWord("RIGHT", (80, 60, 30, 12), 0.9),
    ]
    assert _join(words) == "WORD TM LEFT RIGHT"
    assert _join(words, "rtl") == "TM WORD RIGHT LEFT"


def test_overlapping_boxes_keep_a_word_once():
    ocr = RapidOcr()
    ocr._words = lambda _image: [OcrWord("ONLY", (12, 12, 20, 10), 0.9)]
    outer = TextRegion(1, (0, 0, 100, 100))
    inner = TextRegion(2, (10, 10, 30, 20))
    _direction, regions = ocr.recognize(
        Image.new("RGB", (100, 100), "white"),
        [outer, inner],
    )
    assert regions[0].text == ""
    assert regions[1].text == "ONLY"


def test_action_caption_is_not_a_sign():
    """Короткое название действия в комиксе участвует в обработке звуков."""
    for text in ("Startle", "Whisper", "Squeeze", "Pull", "Kiss", "Nudge", "Poke", "Blush"):
        region = _region(text)
        RapidOcr._guess_type(region)
        assert region.block_type == "sfx"


def test_terminal_free_text_is_not_a_sign():
    """Междометие — звук, фраза с восклицанием — повествование, вывески остаются."""
    for text in ("Hah...", "Ehe!", "Wow?"):
        region = _region(text)
        RapidOcr._guess_type(region)
        assert region.block_type == "sfx", text
    phrase = _region("Yo-urso mean!")
    RapidOcr._guess_type(phrase)
    assert phrase.block_type == "narration"
    for text in ("@ne_go_m", "patreon.com/...", "Follow", "The Reading Time", "Sale"):
        region = _region(text)
        RapidOcr._guess_type(region)
        assert region.block_type == "sign", text


def test_unassigned_ocr_sound_is_kept_without_duplicates_or_signature():
    """Найденный OCR звук не теряется из-за отсутствия бокса детектора."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [
        OcrWord("HELLO", (12, 12, 30, 10), .99),
        OcrWord("Squeeze", (70, 30, 50, 20), .99),
        OcrWord("Squeeze", (70, 30, 50, 20), .99),
        OcrWord("@artist", (5, 130, 60, 10), .99),
        OcrWord("Sale", (70, 80, 30, 10), .99),
        OcrWord("BOOM", (100, 110, 30, 20), .35),
    ]
    original = TextRegion(4, (5, 5, 50, 20))
    _, regions = ocr.recognize(Image.new("RGB", (160, 160), "white"), [original])
    assert [r.text for r in regions] == ["HELLO", "Squeeze"]
    assert regions[1].id == 5
    assert regions[1].block_type == "sfx"
    assert regions[1].bbox == (70, 30, 50, 20)


def test_unassigned_sound_does_not_override_excluded_region():
    """Существующая область, включая ручное исключение, остаётся владельцем слова."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [OcrWord("Startle", (12, 12, 30, 10), .99)]
    original = TextRegion(1, (5, 5, 50, 20), skip=True)
    _, regions = ocr.recognize(Image.new("RGB", (100, 100), "white"), [original])
    assert len(regions) == 1
    assert regions[0].skip


def test_empty_balloon_retries_ocr_on_crop():
    """Пустая короткая реплика получает отдельный шанс, исключённая — нет."""
    ocr = RapidOcr()
    calls = []
    def words(image):
        calls.append(image.size)
        return [] if len(calls) == 1 else [OcrWord("HI...", (3, 3, 15, 10), .99)]
    ocr._words = words
    speech = TextRegion(1, (20, 20, 30, 20), bubble_bbox=(10, 10, 50, 40))
    excluded = TextRegion(2, (70, 20, 20, 20), bubble_bbox=(65, 10, 30, 40), skip=True)
    _, regions = ocr.recognize(Image.new("RGB", (100, 100), "white"), [speech, excluded])
    assert regions[0].text == "HI..."
    assert regions[1].text == ""
    assert calls == [(100, 100), (46, 36)]


def test_hyphenated_fragment_expands_only_overlapping_recovered_sound():
    """Слабый фрагмент строки дополняет звук, но не порождает отдельную маску."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [
        OcrWord("-A", (60, 30, 50, 40), .52),
        OcrWord("DUMP", (55, 50, 60, 45), .99),
        OcrWord("-B", (5, 110, 30, 15), .52),
    ]
    _, regions = ocr.recognize(Image.new("RGB", (160, 160), "white"), [])
    assert len(regions) == 1
    assert regions[0].text == "-A DUMP"
    assert regions[0].bbox == (55, 30, 60, 65)
