"""Метрики глифов typesetter. Раскладка и отрисовка остаются в typesetter.py."""

from __future__ import annotations


def text_width(draw, text: str, font, letter_spacing: float = 0.0) -> int:
    """Ширина строки. Нулевой трекинг считается одним вызовом ``textlength``."""
    if not text:
        return 0
    if not letter_spacing:
        return int(draw.textlength(text, font=font))
    width = 0.0
    last = len(text) - 1
    for index, ch in enumerate(text):
        width += float(draw.textlength(ch, font=font))
        if index != last:
            width += letter_spacing
    return int(round(width))


def line_height(font, size: int) -> int:
    """Высота строки с диакритикой и выносными элементами."""
    try:
        bbox = font.getbbox("ЙАygрд")
        measured = bbox[3] - bbox[1]
    except Exception:
        measured = size
    return max(size, int(measured * 1.15))


def advance(font, size: int, line_spacing: float = 0.0) -> int:
    """Шаг строки. Нулевой ``line_spacing`` не меняет высоту быстрого пути."""
    line_h = line_height(font, size)
    if line_spacing:
        return max(1, int(round(line_h + line_spacing)))
    return line_h
