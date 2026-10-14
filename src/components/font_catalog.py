"""Каталог файлов шрифтов: models/fonts, бандл, каталог пользователя и системные.

Категория выбирается без учёта регистра по подстроке в семействе и имени файла.
Порядок проверок фиксированный: handwritten, затем sfx, затем shout, иначе dialogue.

handwritten: caveat, marck, neucha, pangolin, shantell, bad script, pacifico,
handwriting, script, firsttimewriting, first time writing, vyaz.
sfx: creepster, eater, nosifer, unifraktur, pressstart, press start, special elite,
impact, liber-struct, liber struct, publicpixel, public pixel, pixelzone, deltablock,
delta block, unsightly.
shout: russo, oswald, anton, bebas, bangers, black, display, blaec, napalm,
operationnapalm, operation napalm.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from src.utils.logger import logger
from src.utils.paths import bundle_root, install_root, models_dir, project_root

_FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
_CYRILLIC = range(0x0410, 0x0450)

# Роли автоподстановки. Человекочитаемая таблица — docs/FONTS.md.
FONT_ROLE_DIALOGUE = "Heroika-Regular"
FONT_ROLE_HANDWRITTEN = "FirstTimeWriting"
FONT_ROLE_SHOUT = "Blaec-Regular"
FONT_ROLE_SHOUT_ITALIC = "Blaec-Italic"
FONT_ROLE_STENCIL = "OperationNapalm-Regular"
FONT_ROLE_SFX = "DeltaBlock-Regular"
FONT_ROLE_SFX_TECH = "Liber-Struct"
FONT_ROLE_SFX_COMEDY = "Unsightly"
FONT_ROLE_PIXEL = "Pixelzone"
FONT_ROLE_PIXEL_BOLD = "PublicPixel"
FONT_ROLE_DECOR = "VyazPixel"

# Обратная совместимость со старыми именами в тестах/импортах.
TRIAL_SFX_FONT = FONT_ROLE_SFX
TRIAL_HANDWRITTEN_FONT = FONT_ROLE_HANDWRITTEN
TRIAL_SHOUT_FONT = FONT_ROLE_SHOUT

_LAUGHTER = (
    "хаха",
    "хихи",
    "хех",
    "хохо",
    "haha",
    "hehe",
    "hihi",
    "lol",
    "лол",
    "кек",
)

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
    "firsttimewriting",
    "first time writing",
    "vyaz",
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
    "liber-struct",
    "liber struct",
    "publicpixel",
    "public pixel",
    "pixelzone",
    "deltablock",
    "delta block",
    "unsightly",
)
_SHOUT = (
    "russo",
    "oswald",
    "anton",
    "bebas",
    "bangers",
    "black",
    "display",
    "blaec",
    "napalm",
    "operationnapalm",
    "operation napalm",
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
    include_bundle: bool | None = None,
) -> list[FontFace]:
    """Собрать лица .ttf/.otf/.ttc и отсортировать по id.

    По умолчанию модели берутся из ``models_dir() / "fonts"``.
    Обход: модели, бандл ``src/resources/fonts`` и ``fonts`` рядом с программой,
    затем ``user_dir``, затем системные каталоги.
    id — stem файла. Если он уже занят, id становится ``{источник}-{stem}``,
    где источник — ``models``, ``bundle``, ``user`` или ``system``. Следующие
    совпадения получают суффикс ``-2``, ``-3`` и так далее.

    Бандл подключается, когда ``include_bundle`` истинно. По умолчанию — только
    если ``models_fonts`` не передан (тесты с явным каталогом бандл не видят).
    Системные каталоги читаются только при ``include_system``. Если список
    не передан, берётся ``%WINDIR%/Fonts`` (по умолчанию ``C:\\Windows\\Fonts``).
    Отсутствующий каталог пропускается. Битый файл остаётся в списке
    с ``cyrillic=False`` и семейством из stem.
    """
    models_root = models_dir() / "fonts" if models_fonts is None else Path(models_fonts)
    if include_bundle is None:
        include_bundle = models_fonts is None
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
    if include_bundle:
        for directory in _bundle_font_dirs():
            consume("bundle", directory)
    if user_dir is not None:
        consume("user", Path(user_dir))
    for directory in system_roots:
        consume("system", directory)

    faces.sort(key=lambda face: face.id)
    return faces


def assign_stylized_fonts(
    regions,
    *,
    enabled: bool = True,
    faces: list[FontFace] | None = None,
) -> None:
    """Проставить ``font_id`` по ролям из ``docs/FONTS.md``, если слот пуст.

    Не трогает регионы с уже заданным ``font_id`` или ``edited``.
    Если файл роли отсутствует в каталоге — регион пропускается.
    """
    if not enabled:
        return
    catalog = faces if faces is not None else scan_fonts()
    available = {face.id for face in catalog}
    for region in regions:
        style = getattr(region, "style", None)
        if style is None:
            continue
        if str(getattr(style, "font_id", "") or "").strip():
            continue
        if bool(getattr(region, "edited", False)):
            continue
        font_id = role_font_id(region)
        if not font_id or font_id not in available:
            continue
        style.font_id = font_id


def role_font_id(region) -> str | None:
    """Id шрифта по роли региона. См. ``docs/FONTS.md``."""
    block = str(getattr(region, "block_type", "") or "").strip().lower()
    text = str(getattr(region, "text", "") or "")
    folded = "".join(ch.casefold() for ch in text if not ch.isspace())
    letters = [ch for ch in text if ch.isalpha()]
    uppercase = bool(letters) and all(ch.isupper() for ch in letters)
    has_bubble = getattr(region, "bubble_bbox", None) is not None

    if block == "sfx":
        if _looks_like_laughter(folded):
            return FONT_ROLE_SFX_COMEDY
        if _looks_like_tech_sfx(text, folded):
            return FONT_ROLE_SFX_TECH
        return FONT_ROLE_SFX

    if has_bubble and block in ("dialogue", "narration", ""):
        return FONT_ROLE_DIALOGUE

    if block == "title":
        return FONT_ROLE_SHOUT

    if block == "sign":
        if uppercase:
            return FONT_ROLE_STENCIL
        return FONT_ROLE_HANDWRITTEN

    if block == "noise":
        return FONT_ROLE_PIXEL

    if has_bubble:
        return FONT_ROLE_DIALOGUE

    # Free без баллона.
    if uppercase:
        return FONT_ROLE_SHOUT
    return FONT_ROLE_HANDWRITTEN


def _trial_font_id(region) -> str | None:
    """Устарело: то же, что ``role_font_id``."""
    return role_font_id(region)


def _looks_like_laughter(folded: str) -> bool:
    if not folded:
        return False
    return any(token in folded for token in _LAUGHTER)


def _looks_like_tech_sfx(text: str, folded: str) -> bool:
    """Короткий «кодовый» SFX: цифры или смесь латиницы с цифрами без пробелов."""
    stripped = text.strip()
    if not stripped or len(stripped) > 8:
        return False
    digits = sum(ch.isdigit() for ch in stripped)
    if digits >= 2:
        return True
    if digits >= 1 and any(ch.isascii() and ch.isalpha() for ch in stripped):
        return True
    return False


def _bundle_font_dirs() -> list[Path]:
    """Каталоги встроенных шрифтов (Heroika, CC0-проба)."""
    from src.app.component_catalog import by_id, directory, ready

    extra = by_id("font-pack")
    return ([directory(extra)] if ready(extra) else []) + [
        bundle_root() / "src" / "resources" / "fonts",
        install_root() / "fonts",
        project_root() / "src" / "resources" / "fonts",
    ]


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
