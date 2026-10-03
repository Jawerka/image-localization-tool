"""Утилиты для работы с путями."""

import sys
from pathlib import Path


def project_root() -> Path:
    """Корень репозитория (родитель каталога src)."""
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    """Каталог ресурсов PyInstaller или корень репозитория."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return project_root()


def install_root() -> Path:
    """Папка с exe в сборке или корень репозитория."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def models_dir(override: str | Path | None = None) -> Path:
    """Каталог моделей: явный путь, models рядом с программой или в репозитории."""
    if override:
        return Path(override)
    installed = install_root() / "models"
    if installed.is_dir():
        return installed
    return project_root() / "models"


def resolve_model(filename: str, override: str | Path | None = None) -> Path:
    """Первый существующий файл модели. Если файла нет — последний кандидат."""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override) / filename)
    candidates.append(install_root() / "models" / filename)
    candidates.append(bundle_root() / "models" / filename)
    candidates.append(project_root() / "models" / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def resolve_font(filename: str) -> Path:
    """Шрифт в бандле, рядом с программой или в src/resources/fonts."""
    candidates = [
        bundle_root() / "src" / "resources" / "fonts" / filename,
        install_root() / "fonts" / filename,
        project_root() / "src" / "resources" / "fonts" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def get_resource_path(*parts: str) -> Path:
    """Получить путь к ресурсу относительно директории проекта."""
    return Path(__file__).parent.parent / "resources" / Path(*parts)


def get_font_path(font_name: str) -> Path:
    """Получить путь к шрифту."""
    return get_resource_path("fonts", font_name)


def ensure_dir(path: str | Path) -> Path:
    """Убедиться, что директория существует."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_output_path(source_path: str, suffix: str = "_translated") -> str:
    """Сгенерировать путь для выходного файла."""
    path = Path(source_path)
    return str(path.parent / f"{path.stem}{suffix}{path.suffix}")
