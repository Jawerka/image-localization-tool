"""Прозрачность фолбэков: статус offline только для OCR/Argos, не для OpenCV."""

from __future__ import annotations

from src.app.worker import _mentions_fallback


def test_mentions_fallback_for_ocr_and_argos():
    assert _mentions_fallback(["OCR переключён на RapidOCR: down"])
    assert _mentions_fallback(["Перевод переключён на Argos: down"])
    assert _mentions_fallback(["Сервер LLM недоступен, используется RapidOCR + Argos"])


def test_mentions_fallback_ignores_opencv_only():
    assert not _mentions_fallback([])
    assert not _mentions_fallback(["Очистка переключена на OpenCV (LaMa недоступна): boom"])
    assert not _mentions_fallback(["Текст не влез полностью: 1"])
