"""Встроенный словарь звукоподражаний комикса."""

from __future__ import annotations

import unicodedata

# Короткие русские звукоподражания. Ключи — английский крик заглавными.
_GLOSSARY: dict[str, str] = {
    "BANG": "БАМ",
    "BOOM": "БУМ",
    "CRASH": "БАЦ",
    "POW": "БАХ",
    "WHAM": "ХРЯСЬ",
    "SLAM": "ХЛОП",
    "THUD": "БУХ",
    "CLICK": "ЩЁЛК",
    "SPLASH": "ПЛЮХ",
    "DRIP": "КАП",
    "WHOOSH": "ВЖУХ",
    "RUMBLE": "ГРРР",
    "CRACK": "ТРЕСК",
    "KABOOM": "БАБАХ",
    "GASP": "АХ",
    "SIGH": "ЭХ",
    "HA": "ХА",
    "HEH": "ХЕ",
    "UGH": "УГХ",
    "OW": "АЙ",
    "AARGH": "ААА",
    "SNIFF": "ШМЫГ",
    "CHOMP": "ХРУМ",
    "RUSTLE": "ШУРХ",
    "TAP": "ТУК",
    "KNOCK": "СТУК",
    "ZAP": "БЗЗ",
    "BOING": "БОЙНГ",
    "BAM": "БАМ",
    "SMASH": "КРАХ",
    "CRUNCH": "ХРУСТ",
    "SNAP": "ХРУП",
    "HISS": "ШШШ",
    "ROAR": "РРР",
    "THUMP": "ТУМ",
    "PLOP": "ШЛЁП",
    "SQUEAK": "ПИСК",
    "GRUNT": "ХРР",
}


def _is_edge_junk(ch: str) -> bool:
    """Пробел или знак препинания по краю токена."""
    return ch.isspace() or unicodedata.category(ch).startswith("P")


def _normalize(text: str) -> str:
    """Снять пробелы и пунктуацию по краям, ключ — в верхнем регистре."""
    token = text.strip()
    while token and _is_edge_junk(token[0]):
        token = token[1:]
    while token and _is_edge_junk(token[-1]):
        token = token[:-1]
    return token.upper()


def lookup(text: str) -> str | None:
    """Русское звукоподражание или None, если слова нет в словаре.

    Регистр не важен. Пробелы и пунктуация по краям отбрасываются.
    Пустая строка даёт None.
    """
    key = _normalize(text)
    if not key:
        return None
    return _GLOSSARY.get(key)


def as_glossary() -> dict[str, str]:
    """Копия словаря: ключи — английские токены в верхнем регистре."""
    return dict(_GLOSSARY)
