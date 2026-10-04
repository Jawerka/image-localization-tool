"""Чужая письменность в переводе и маршрут Argos."""

from src.components.lang_guard import foreign_leak, route_for_argos


def test_english_sentence_leaks_into_russian():
    assert foreign_leak("Hello there friend", "ru") is True


def test_quoted_english_inside_russian_is_kept():
    assert foreign_leak("Он сказал «Hello there» и ушёл", "ru") is False


def test_name_and_short_token_inside_russian_are_kept():
    assert foreign_leak("Я пошёл к Kirby, OK", "ru") is False
    assert foreign_leak("OK", "ru") is False


def test_latin_block_leaks_into_russian():
    assert foreign_leak("This is English", "ru") is True


def test_hangul_leaks_into_english():
    assert foreign_leak("안녕하세요", "en") is True


def test_argos_does_not_flip_target_script():
    assert route_for_argos("Привет", "ru").skip is True
    assert route_for_argos("Hello", "ru").source == "en"
    assert route_for_argos("こんにちは", "ru").uncovered is True
    assert route_for_argos("Hello", "en").skip is True
