"""Нейтральный вход к установленным моделям и языкам для CLI и компонентов."""

from __future__ import annotations

from pathlib import Path


def installed_file(filename: str) -> Path | None:
    from src.app.component_catalog import installed_file as impl

    return impl(filename)


def language_dirs() -> list[Path]:
    from src.app.component_catalog import language_dirs as impl

    return impl()


def ocr_params() -> dict:
    from src.app.component_catalog import ocr_params as impl

    return impl()


def catalog_by_id(component_id: str):
    from src.app.component_catalog import by_id

    return by_id(component_id)


def catalog_directory(component):
    from src.app.component_catalog import directory

    return directory(component)


def catalog_ready(component) -> bool:
    from src.app.component_catalog import ready

    return ready(component)


def configure_argos_paths() -> None:
    from src.app.runtime import configure_argos_paths as impl

    impl()
