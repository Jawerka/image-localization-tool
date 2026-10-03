"""Мост к системным диалогам.

Окно приложения подставляет свою реализацию. Здесь нет tkinter и pywebview:
базовые методы ничего не открывают и не возвращают выбранных путей.
Пути в интерфейс приходят только отсюда, страница их не присылает.
"""

from __future__ import annotations

from pathlib import Path


class DialogBridge:
    """Пустая реализация диалогов. Тесты и окно подменяют экземпляр целиком."""

    def open_files(self) -> list[Path]:
        """Файлы страниц. Пустой список — отмена."""
        return []

    def open_folder(self) -> Path | None:
        """Папка со страницами. None — отмена."""
        return None

    def pick_directory(self) -> Path | None:
        """Папка экспорта. None — отмена."""
        return None

    def reveal(self, path: Path) -> None:
        """Показать путь в проводнике."""
        return None

    def open_log(self) -> None:
        """Открыть журнал приложения."""
        return None
