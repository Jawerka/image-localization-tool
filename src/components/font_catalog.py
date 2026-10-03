"""Каталог файлов шрифтов: models/fonts, каталог пользователя и системные папки.

Категория выбирается без учёта регистра по подстроке в семействе и имени файла.
Порядок проверок фиксированный: handwritten, затем sfx, затем shout, иначе dialogue.

handwritten: caveat, marck, neucha, pangolin, shantell, bad script, pacifico,
handwriting, script.
sfx: creepster, eater, nosifer, unifraktur, pressstart, press start, special elite,
impact.
shout: russo, oswald, anton, bebas, bangers, black, display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from src.utils.logger import logger
from src.utils.paths import models_dir

_FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
_CYRILLIC = range(0x0410, 0x0450)

_HANDWRITTEN = (
    "caveat",
    "marck",
    "neucha",
    "pangolin",
    "shantell",
    "bad script",
    "pacifico",
    "handwriting",
    "script",
)
_SFX = (
    "creepster",
    "eater",
    "nosifer",
    "unifraktur",
    "pressstart",
    "press start",
    "special elite",
    "impact",
)
_SHOUT = (
    "russo",
    "oswald",
    "anton",
    "bebas",
    "bangers",
    "black",
    "display",
)


@dataclass(frozen=True)
class FontFace:
    id: str
    family: str
    path: str
    category: str  # dialogue|shout|sfx|handwritten
    cyrillic: bool


def has_cyrillic(path: str | Path) -> bool:
    """True, если cmap покрывает весь блок U+0410..U+044F.

    Для TTC проверяется любое лицо. Ошибка чтения или битый файл дают False.
    """
    return _read_face(Path(path))[1]


def categorize(family: str, filename: str = "") -> str:
    """Категория по семейству и имени файла. См. docstring модуля."""
    haystack = f"{family} {filename}".casefold()
    if _has_keyword(haystack, _HANDWRITTEN):
        return "handwritten"
    if _has_keyword(haystack, _SFX):
        return "sfx"
    if _has_keyword(haystack, _SHOUT):
        return "shout"
    return "dialogue"


def scan_fonts(
    models_fonts: Path | None = None,
    user_dir: Path | None = None,
    system_dirs: list[Path] | None = None,
    include_system: bool = True,
) -> list[FontFace]:
    """Собрать лица .ttf/.otf/.ttc и отсортировать по id.

    По умолчанию модели берутся из ``models_dir() / "fonts"``.
    Обход: модели, затем ``user_dir``, затем системные каталоги.
    id — stem файла. Если он уже занят, id становится ``{источник}-{stem}``,
    где источник — ``models``, ``user`` или ``system``. Следующие совпадения
    получают суффикс ``-2``, ``-3`` и так далее.

    Системные каталоги читаются только при ``include_system``. Если список
    не передан, берётся ``%WINDIR%/Fonts`` (по умолчанию ``C:\\Windows\\Fonts``).
    Отсутствующий каталог пропускается. Битый файл остаётся в списке
    с ``cyrillic=False`` и семейством из stem.
    """
    models_root = models_dir() / "fonts" if models_fonts is None else Path(models_fonts)
    if not include_system:
        system_roots: list[Path] = []
    elif system_dirs is None:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        system_roots = [Path(windir) / "Fonts"]
    else:
        system_roots = [Path(item) for item in system_dirs]

    used_ids: set[str] = set()
    seen_paths: set[str] = set()
    faces: list[FontFace] = []

    def consume(source: str, directory: Path) -> None:
        for path in _iter_font_files(directory):
            key = _path_key(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            family, cyrillic = _read_face(path)
            faces.append(
                FontFace(
                    id=_unique_id(path.stem or path.name, source, used_ids),
                    family=family,
                    path=_path_str(path),
                    category=categorize(family, path.name),
                    cyrillic=cyrillic,
                )
            )

    consume("models", models_root)
    if user_dir is not None:
        consume("user", Path(user_dir))
    for directory in system_roots:
        consume("system", directory)

    faces.sort(key=lambda face: face.id)
    return faces


def find_font(font_id: str, faces: list[FontFace] | None = None) -> FontFace | None:
    """Найти лицо по точному id. Пустой id даёт None и не запускает обход."""
    if not font_id:
        return None
    if faces is None:
        faces = scan_fonts()
    for face in faces:
        if face.id == font_id:
            return face
    return None


def resolve_font_path(font_id: str, faces: list[FontFace] | None = None) -> Path | None:
    """Путь к файлу шрифта для вёрстки или None, если id не найден."""
    face = find_font(font_id, faces)
    if face is None:
        return None
    return Path(face.path)


def _has_keyword(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in haystack for keyword in keywords)


def _unique_id(stem: str, source: str, used: set[str]) -> str:
    if stem not in used:
        used.add(stem)
        return stem
    base = f"{source}-{stem}"
    if base not in used:
        used.add(base)
        return base
    number = 2
    while f"{base}-{number}" in used:
        number += 1
    candidate = f"{base}-{number}"
    used.add(candidate)
    return candidate


def _iter_font_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    found: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        logger.debug("Не удалось прочитать каталог шрифтов %s", directory, exc_info=True)
        return []
    for entry in entries:
        try:
            if entry.is_file() and entry.suffix.lower() in _FONT_SUFFIXES:
                found.append(entry)
        except OSError:
            continue
    found.sort(key=lambda item: item.name.casefold())
    return found


def _path_str(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _path_key(path: Path) -> str:
    return _path_str(path).casefold()


def _read_face(path: Path) -> tuple[str, bool]:
    fallback = path.stem or path.name
    opener = None
    try:
        fonts, opener = _load_fonts(path)
        family = fallback
        named = False
        cyrillic = False
        for font in fonts:
            if not named:
                try:
                    family = _family_name(font, fallback)
                    named = True
                except Exception:
                    logger.debug("Не удалось прочитать имя шрифта %s", path, exc_info=True)
            try:
                if _cmap_has_cyrillic(font):
                    cyrillic = True
            except Exception:
                logger.debug("Не удалось прочитать cmap %s", path, exc_info=True)
        return family, cyrillic
    except Exception:
        logger.debug("Не удалось открыть шрифт %s", path, exc_info=True)
        return fallback, False
    finally:
        if opener is not None:
            try:
                opener.close()
            except Exception:
                logger.debug("Не удалось закрыть шрифт %s", path, exc_info=True)


def _load_fonts(path: Path):
    """Открыть имя и cmap, не разбирая глифы. Иначе каталог Windows держит процесс десятки секунд."""
    location = str(path)
    if path.suffix.lower() == ".ttc":
        collection = TTCollection(location, lazy=True)
        return list(collection.fonts), collection
    font = TTFont(location, lazy=True)
    return [font], font


def _family_name(font: TTFont, fallback: str) -> str:
    table = font.get("name")
    if table is None:
        return fallback
    for name_id in (16, 1):
        value = table.getDebugName(name_id)
        if value and str(value).strip():
            return str(value).strip()
    return fallback


def _cmap_has_cyrillic(font: TTFont) -> bool:
    needed = set(_CYRILLIC)
    covered: set[int] = set()
    table = font.get("cmap")
    if table is None:
        return False
    for subtable in table.tables:
        mapping = getattr(subtable, "cmap", None)
        if not mapping:
            continue
        covered.update(int(codepoint) for codepoint in mapping)
        if needed <= covered:
            return True
    return False
