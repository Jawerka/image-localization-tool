"""Письменность перевода: чужой язык в блоке и пара для Argos.

Имена с заглавной и слова из одних заглавных не голосуют за латиницу.
Кавычки и строки глоссария из подсчёта вырезаются.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_CYRILLIC_TARGETS = frozenset({"ru", "uk"})
_QUOTE_RE = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")
_SENTENCE_MARK_RE = re.compile(r"[.!?…\n\r]")
_FOREIGN_SHARE = 0.25
_FOREIGN_LETTERS = 4


def foreign_leak(text: str, target_lang: str, allowed: list[str] | None = None) -> bool:
    """True, если после исключений в тексте заметна не та письменность.

    Пустая строка и текст только из имён, коротких токенов и кавычек — не чужой.
    """
    cleaned = _strip(text, allowed or [])
    cyr, lat, other = _counted_letters(cleaned)
    code = (target_lang or "").strip().lower()
    if code in _CYRILLIC_TARGETS:
        foreign = lat + other
        home = cyr
    elif code == "en":
        foreign = cyr + other
        home = lat
    else:
        foreign = other
        home = cyr + lat
    total = home + foreign
    if total == 0 or foreign == 0:
        return False
    if home == 0:
        return True
    return foreign >= _FOREIGN_LETTERS and (foreign / total) >= _FOREIGN_SHARE


@dataclass(frozen=True)
class ArgosRoute:
    """Куда отдать блок офлайн-переводчику."""

    source: str = ""
    skip: bool = False
    uncovered: bool = False


def route_for_argos(text: str, target_lang: str) -> ArgosRoute:
    """Кириллица → ``ru``, латиница → ``en``. Уже цель — ``skip``. Иероглифы и хангыль — ``uncovered``.

    Переворота пары нет: блок на письменности цели не уходит в Argos.
    """
    cyr, lat, other = _raw_letters(text or "")
    code = (target_lang or "").strip().lower()
    if other > cyr and other > lat and other > 0:
        return ArgosRoute(uncovered=True)
    if cyr == 0 and lat == 0:
        return ArgosRoute(skip=True)
    cyrillic = cyr >= lat
    if cyrillic:
        if code in _CYRILLIC_TARGETS:
            return ArgosRoute(skip=True)
        return ArgosRoute(source="ru")
    if code == "en":
        return ArgosRoute(skip=True)
    return ArgosRoute(source="en")


def _strip(text: str, allowed: list[str]) -> str:
    cleaned = _QUOTE_RE.sub(" ", text or "")
    for item in allowed:
        token = str(item or "").strip()
        if token:
            cleaned = cleaned.replace(token, " ")
    return cleaned


def _is_letter(ch: str) -> bool:
    return unicodedata.category(ch).startswith("L")


def _script(ch: str) -> str:
    if not _is_letter(ch):
        return ""
    code = ord(ch)
    if (
        0x0400 <= code <= 0x052F
        or 0x1C80 <= code <= 0x1C8F
        or 0x2DE0 <= code <= 0x2DFF
        or 0xA640 <= code <= 0xA69F
    ):
        return "cyr"
    if (
        0x0041 <= code <= 0x005A
        or 0x0061 <= code <= 0x007A
        or 0x00C0 <= code <= 0x024F
        or 0x1E00 <= code <= 0x1EFF
    ):
        return "lat"
    return "other"


def _is_word_char(ch: str) -> bool:
    return _is_letter(ch) or unicodedata.category(ch).startswith("N") or ch in {"_", "'", "’"}


def _raw_letters(text: str) -> tuple[int, int, int]:
    cyr = lat = other = 0
    for ch in text or "":
        script = _script(ch)
        if script == "cyr":
            cyr += 1
        elif script == "lat":
            lat += 1
        elif script == "other":
            other += 1
    return cyr, lat, other


def _counted_letters(text: str) -> tuple[int, int, int]:
    """Латиница без имён, слов из заглавных и токенов короче 4 букв."""
    cyr = lat = other = 0
    sentence_start = True
    i = 0
    n = len(text)
    while i < n:
        if not _is_word_char(text[i]):
            if _SENTENCE_MARK_RE.match(text[i]):
                sentence_start = True
            i += 1
            continue
        start = i
        while i < n and _is_word_char(text[i]):
            i += 1
        token_cyr, token_lat, token_other = _count_token(text[start:i], sentence_start)
        cyr += token_cyr
        lat += token_lat
        other += token_other
        sentence_start = False
    return cyr, lat, other


def _count_token(token: str, sentence_start: bool) -> tuple[int, int, int]:
    cyr = other = 0
    latin: list[str] = []
    has_digit = False
    for ch in token:
        if unicodedata.category(ch).startswith("N") or ch == "_":
            has_digit = True
            continue
        if ch in {"'", "’"}:
            continue
        script = _script(ch)
        if script == "cyr":
            cyr += 1
        elif script == "lat":
            latin.append(ch)
        elif script == "other":
            other += 1
    lat = 0
    if latin and not has_digit and len(latin) >= _FOREIGN_LETTERS:
        uppers = sum(1 for ch in latin if ch.isupper())
        proper = latin[0].isupper() and not sentence_start
        all_caps = uppers == len(latin) and len(latin) >= 2
        if not (all_caps or proper):
            lat = len(latin)
    return cyr, lat, other
