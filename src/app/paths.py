"""Каталоги данных настольного приложения.

Портативный режим: если рядом с программой есть каталог ``data``, настройки,
проекты, кэш и лог лежат в нём. Иначе на Windows настройки — в ``%APPDATA%``,
а проекты, кэш и лог — в ``%LOCALAPPDATA%``. Каталоги создаются при записи,
не при импорте.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from src.utils.paths import install_root

APP_DIR_NAME = "ImageLocalizationTool"

_current: ContextVar[AppPaths | None] = ContextVar("ilt_app_paths", default=None)


@dataclass(frozen=True)
class AppPaths:
    """Явные корни для приложения и тестов.

    ``portable=True`` — всё внутри ``root`` (это уже каталог ``data``).
    ``portable=False`` — ``root`` хранит проекты, кэш и лог, а настройки
    лежат в ``settings_root`` (если не задан, тоже в ``root``).
    """

    root: Path
    portable: bool = True
    settings_root: Path | None = None

    def settings_path(self) -> Path:
        if self.portable:
            return self.root / "settings.json"
        base = self.settings_root if self.settings_root is not None else self.root
        return base / "settings.json"

    def projects_dir(self) -> Path:
        return self.root / "projects"

    def logs_dir(self) -> Path:
        return self.root / "logs"

    def cache_dir(self) -> Path:
        return self.root / "cache"


def default_paths() -> AppPaths:
    """Корни по установке и переменным среды. Каталоги не создаёт."""
    data = install_root() / "data"
    if data.is_dir():
        return AppPaths(root=data, portable=True)
    if sys.platform == "win32":
        roaming = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        roaming_root = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
        local_root = Path(local) if local else Path.home() / "AppData" / "Local"
        return AppPaths(
            root=local_root / APP_DIR_NAME,
            portable=False,
            settings_root=roaming_root / APP_DIR_NAME,
        )
    home = Path.home() / ".image-localization-tool"
    return AppPaths(root=home, portable=False, settings_root=home)


def _resolve(paths: AppPaths | None = None) -> AppPaths:
    if paths is not None:
        return paths
    current = _current.get()
    if current is not None:
        return current
    return default_paths()


@contextmanager
def using_paths(paths: AppPaths):
    """Подменить корни на время блока. После выхода предыдущее значение возвращается."""
    token = _current.set(paths)
    try:
        yield paths
    finally:
        _current.reset(token)


def data_root(paths: AppPaths | None = None) -> Path:
    """Корень проектов, кэша и лога. В портативном режиме — каталог ``data``."""
    return _resolve(paths).root


def settings_path(paths: AppPaths | None = None) -> Path:
    return _resolve(paths).settings_path()


def projects_dir(paths: AppPaths | None = None) -> Path:
    return _resolve(paths).projects_dir()


def logs_dir(paths: AppPaths | None = None) -> Path:
    return _resolve(paths).logs_dir()


def cache_dir(paths: AppPaths | None = None) -> Path:
    return _resolve(paths).cache_dir()


def is_portable(paths: AppPaths | None = None) -> bool:
    return _resolve(paths).portable
