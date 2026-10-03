"""Словарь звукоподражаний комикса."""

from src.components.sfx_dict import as_glossary, lookup

_REQUIRED = (
    "BANG",
    "BOOM",
    "CRASH",
    "POW",
    "WHAM",
    "SLAM",
    "THUD",
    "CLICK",
    "SPLASH",
    "DRIP",
    "WHOOSH",
    "RUMBLE",
    "CRACK",
    "KABOOM",
    "GASP",
    "SIGH",
    "HA",
    "HEH",
    "UGH",
    "OW",
    "AARGH",
    "SNIFF",
    "CHOMP",
    "RUSTLE",
    "TAP",
    "KNOCK",
    "ZAP",
    "BOING",
)


def test_lookup_bang_matches_glossary():
    """Bang! совпадает с русской записью BANG."""
    assert lookup("Bang!") == "БАМ"
    assert lookup("Bang!") == as_glossary()["BANG"]


def test_lookup_unknown_returns_none():
    """Неизвестное и пустое слово не переводятся."""
    assert lookup("hello") is None
    assert lookup("") is None


def test_lookup_ignores_case_and_punctuation():
    """Регистр и пунктуация по краям не мешают поиску."""
    assert lookup("  BANG...") == lookup("bang") == "БАМ"


def test_as_glossary_has_required_keys_and_returns_copy():
    """Словарь содержит обязательные ключи и отдаёт копию."""
    glossary = as_glossary()
    for key in _REQUIRED:
        assert key in glossary
    glossary["BANG"] = "ИЗМЕНЕНО"
    assert as_glossary()["BANG"] == "БАМ"
