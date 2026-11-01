"""Подготовка текста preview. HTTP-обёртка остаётся в server."""

from __future__ import annotations


def preview_text(query: dict | None) -> str:
    raw = ""
    values = query.get("text") if query else None
    if values:
        raw = values[0]
    text = str(raw or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        text = "Привет"
    return text[:40]
