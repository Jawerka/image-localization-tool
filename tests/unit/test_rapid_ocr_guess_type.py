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


def test_caps_sentence_is_not_a_sound():
    """Короткая фраза заглавными не получает маску звукоподражания."""
    region = _region('YOUR LUNCH SWEETHEART.')
    RapidOcr._guess_type(region)
    assert region.block_type == 'narration'
    for text in ('BA- DUMP', 'BANG BANG', 'HA HA HA!', 'BANG BOOM CRASH!'):
        sound = _region(text)
        RapidOcr._guess_type(sound)
        assert sound.block_type == 'sfx', text


def test_uppercase_author_address_stays_a_sign():
    """Регистр адреса автора не превращает его в звук."""
    for text in ('WWW.ART.COM', '@ARTIST'):
        region = _region(text)
        RapidOcr._guess_type(region)
        assert region.block_type == 'sign'


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


def test_unassigned_line_becomes_one_free_region():
    """Три неназначенных слова на одной линии собираются в свободный регион."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [
        OcrWord("ON", (10, 40, 20, 12), .99),
        OcrWord("THE", (35, 40, 28, 12), .99),
        OcrWord("WALL", (68, 40, 40, 12), .99),
    ]
    _, regions = ocr.recognize(Image.new("RGB", (160, 80), "white"), [])
    assert len(regions) == 1
    assert regions[0].text == "ON THE WALL"
    assert regions[0].class_name == "text_free"
    assert regions[0].bbox == (10, 40, 98, 12)


def test_vertical_column_reads_top_to_bottom():
    """Столбец из трёх высоких глифов читается сверху вниз, даже при сдвиге по X."""
    words = [
        OcrWord("A", (16, 10, 14, 40), 0.9),
        OcrWord("B", (12, 28, 14, 40), 0.9),
        OcrWord("C", (14, 46, 14, 40), 0.9),
    ]
    assert _join(words) == "A B C"


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


def test_empty_free_region_retries_ocr_on_crop():
    """Пустой свободный бланк тоже дочитывается кропом, не только баллон."""
    ocr = RapidOcr()
    calls = []
    def words(image):
        calls.append(image.size)
        return [] if len(calls) == 1 else [OcrWord("LINDA", (4, 4, 40, 12), .99)]
    ocr._words = words
    form = TextRegion(1, (20, 20, 50, 20), class_name="text_free", block_type="narration")
    _, regions = ocr.recognize(Image.new("RGB", (100, 100), "white"), [form])
    assert regions[0].text == "LINDA"
    assert calls == [(100, 100), (66, 36)]


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


def test_slanted_ocr_quads_keep_line_order():
    """Наклонные строки реального баллона не сортируются по левому краю."""
    rows = [
        ("I WIN AGAIN!", ((529, 13), (630, 48), (622, 68), (522, 33))),
        ("HUMAN YOU", ((525, 31), (616, 63), (610, 82), (518, 50))),
        ("ARE PATHETIC IN", ((502, 41), (627, 86), (620, 106), (495, 61))),
        ("VIDEOGAMES...", ((504, 61), (616, 101), (609, 121), (497, 81))),
    ]
    ocr = RapidOcr()
    words = []
    for text, quad in rows:
        ocr._append_word(words, quad, text, .99)
    assert _join(words) == "I WIN AGAIN! HUMAN YOU ARE PATHETIC IN VIDEOGAMES..."


def test_empty_nested_balloon_retry_keeps_word_owner():
    """Повторное распознавание большого баллона не дублирует малый."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [OcrWord("ONLY", (12, 12, 20, 10), .99)]
    outer = TextRegion(1, (0, 0, 100, 100), bubble_bbox=(0, 0, 100, 100))
    inner = TextRegion(2, (10, 10, 30, 20), bubble_bbox=(5, 5, 50, 30))
    _, regions = ocr.recognize(Image.new("RGB", (100, 100), "white"), [outer, inner])
    assert [r.text for r in regions] == ["", "ONLY"]


def test_empty_balloon_retry_preserves_rtl():
    """Направление колонок сохраняется при повторном кропе."""
    ocr = RapidOcr()
    calls = []
    def words(_image):
        calls.append(1)
        return [] if len(calls) == 1 else [
            OcrWord("LEFT", (10, 10, 10, 40), .99),
            OcrWord("RIGHT", (25, 10, 10, 40), .99),
        ]
    ocr._words = words
    region = TextRegion(1, (0, 0, 60, 60), bubble_bbox=(0, 0, 60, 60))
    _, regions = ocr.recognize(Image.new("RGB", (100, 100), "white"), [region], "rtl")
    assert regions[0].text == "RIGHT LEFT"


def test_assigned_ocr_expands_clipped_source_without_changing_balloon():
    """Надёжный OCR восстанавливает края исходных букв для ретуши."""
    ocr = RapidOcr()
    ocr._words = lambda _image: [OcrWord("FUFU", (47, 28, 206, 117), .99)]
    region = TextRegion(1, (56, 44, 160, 86), bubble_bbox=(5, 0, 275, 199))
    _, regions = ocr.recognize(Image.new("RGB", (300, 220), "white"), [region])
    assert regions[0].bbox == (47, 28, 206, 117)
    assert regions[0].bubble_bbox == (5, 0, 275, 199)


def test_source_expansion_preserves_saved_geometry_and_rejects_weak_words():
    """Ручная геометрия и слабые либо слишком большие рамки сохраняются."""
    for attributes in (dict(manual=True), dict(edited=True), dict(layout_snapshot={}),
                       dict(auto_layout={}), dict(text_position=(2, 3))):
        region = TextRegion(1, (10, 10, 20, 20), **attributes)
        RapidOcr._expand_source_bbox(region, [OcrWord("HI", (8, 8, 24, 24), .99)], (100, 100))
        assert region.bbox == (10, 10, 20, 20)
    for word in (OcrWord("HI", (8, 8, 24, 24), .7), OcrWord("HI", (0, 0, 40, 40), .99)):
        region = TextRegion(1, (10, 10, 20, 20))
        RapidOcr._expand_source_bbox(region, [word], (100, 100))
        assert region.bbox == (10, 10, 20, 20)


def test_source_expansion_caps_combined_area():
    """Несколько слов вместе не раздувают исходную область ретуши."""
    region = TextRegion(1, (10, 10, 20, 20))
    words = [OcrWord("ONE", (0, 10, 30, 20), .99), OcrWord("TWO", (10, 0, 20, 30), .99)]
    RapidOcr._expand_source_bbox(region, words, (100, 100))
    assert region.bbox == (10, 10, 20, 20)
