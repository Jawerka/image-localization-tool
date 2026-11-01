"""Исполнение отдельных видов заданий. Lifecycle процесса остаётся в worker."""

from __future__ import annotations


def run_export(job: dict, ctx):
    """Первый вынесенный вид: экспорт готовых страниц."""
    from src.app.worker import _run_export

    return _run_export(job, ctx)
