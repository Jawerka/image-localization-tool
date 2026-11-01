"""Текст образца шрифта готовится вне HTTP."""

from src.app.preview_service import preview_text


def test_preview_text_trims_and_limits():
    assert preview_text({"text": ["  привет\nмир  "]}) == "привет мир"
    assert preview_text({"text": [""]}) == "Привет"
    assert len(preview_text({"text": ["x" * 80]})) == 40
