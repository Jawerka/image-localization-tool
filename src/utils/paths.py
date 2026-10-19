"""Утилиты для работы с путями."""

import os
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
    """Папка с exe в сборке или корень репозитория.

    ``ILT_INSTALL_ROOT`` задаёт корень явно: Flutter-хост ставит его сайдкару,
    который лежит в ``sidecar\\``, а модели, шрифты и ``web`` — в корне установки.
    """
    override = os.environ.get("ILT_INSTALL_ROOT", "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        return directory.parent if directory.name == "sidecar" else directory
    return project_root()


def _legacy_components_root() -> Path | None:
    """Прежний общий каталог компонентов обычной Windows-установки."""
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "ImageLocalizationTool" / "components"


def _adopt_legacy_components(current: Path) -> None:
    """Читать старый каталог без скрытой перекачки, если новый ещё пуст."""
    legacy = _legacy_components_root()
    if legacy is None or not legacy.is_dir() or os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT"):
        return
    if os.path.normcase(os.path.abspath(str(legacy))) == os.path.normcase(os.path.abspath(str(current))):
        return
    os.environ["ILT_COMPONENT_PREVIOUS_ROOT"] = str(legacy)


def components_root() -> Path:
    """Компоненты лежат в папке программы; старые пути читаются отдельно."""
    explicit = os.environ.get("ILT_COMPONENT_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    installed = install_root()
    if not getattr(sys, "frozen", False):
        return installed
    _adopt_legacy_components(installed)
    return installed


def models_dir(override: str | Path | None = None) -> Path:
    """Каталог моделей: явный путь, models рядом с программой или в репозитории.

    В сборке каталог ``models`` рядом с программой создаётся при первом
    обращении: портативная раскладка и серверный деплой кладут модели туда.
    """
    if override:
        return Path(override)
    installed = components_root() / "models"
    if installed.is_dir():
        return installed
    if getattr(sys, "frozen", False):
        installed.mkdir(parents=True, exist_ok=True)
        return installed
    return installed


def resolve_model(filename: str, override: str | Path | None = None) -> Path:
    """Первый существующий файл модели. Если файла нет — последний кандидат."""
    candidates: list[Path] = []
    from src.app.component_catalog import installed_file

    external = installed_file(filename)
    if external is not None:
        candidates.append(external)
    if override:
        candidates.append(Path(override) / filename)
    candidates.append(components_root() / "models" / filename)
    candidates.append(install_root() / "models" / filename)
    candidates.append(bundle_root() / "models" / filename)
    candidates.append(project_root() / "models" / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def resolve_font(filename: str) -> Path:
    """Шрифт в бандле, рядом с программой или в src/resources/fonts."""
    from src.app.component_catalog import installed_file

    external = installed_file(filename)
    candidates = ([external] if external is not None else []) + [
        components_root() / "fonts" / filename,
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
