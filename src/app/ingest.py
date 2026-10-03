"""Импорт изображений: список файлов, распаковка архива и план глав.

Чистые функции без хранилища и без моделей. Типичный вызов:

- папка: ``list_images(root, recursive)``, затем
  ``plan_chapters(paths, mode, root=root)``;
- zip/cbz: ``extract_archive(archive, dest)``, затем
  ``plan_chapters(paths, mode, root=dest, archive_stem=archive.stem)``.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
ARCHIVE_SUFFIXES = frozenset({".zip", ".cbz"})

_DIGIT_RUN = re.compile(r"(\d+)")
# Путь не под корнем импорта. Это не то же самое, что файл прямо в корне.
_OUTSIDE = object()


def natural_sort_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """Ключ порядка, в котором «2» раньше «10».

    Строка режется на серии цифр и прочий текст. Цифры сравниваются как
    целые, остальные куски — после ``casefold``.
    """
    key: list[tuple[int, int | str]] = []
    for chunk in _DIGIT_RUN.split(str(text).casefold()):
        if chunk.isdigit():
            key.append((0, int(chunk)))
        else:
            key.append((1, chunk))
    return tuple(key)


def is_image(path: Path) -> bool:
    """Расширение png, jpg, jpeg, bmp, tif или tiff без учёта регистра."""
    return Path(path).suffix.casefold() in IMAGE_SUFFIXES


def is_archive(path: Path) -> bool:
    """Суффикс zip или cbz без учёта регистра. Содержимое не проверяется."""
    return Path(path).suffix.casefold() in ARCHIVE_SUFFIXES


def list_images(root: Path, recursive: bool) -> list[Path]:
    """Изображения каталога в естественном порядке.

    ``recursive=False`` смотрит только сам каталог, без подпапок.
    ``recursive=True`` обходит подпапки. Каталоги и прочие не-файлы
    пропускаются. Если ``root`` нет или это не каталог, результат пустой.
    Ключ сортировки — ``natural_sort_key`` относительного пути через ``/``.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    walker = root.rglob("*") if recursive else root.iterdir()
    for path in walker:
        if path.is_file() and is_image(path):
            found.append(path)
    found.sort(key=lambda path: natural_sort_key(path.relative_to(root).as_posix()))
    return found


def extract_archive(archive: Path, dest: Path) -> list[Path]:
    """Извлечь изображения из zip или cbz в ``dest``.

    CBZ открывается тем же ``zipfile``. Записи-каталоги и не-изображения
    пропускаются. Безопасный относительный путь внутри архива сохраняется,
    поэтому папка главы не теряется. ``dest`` создаётся, если его ещё нет.

    Zip-slip: член с абсолютным путём, префиксом диска, UNC или ``..``,
    который после нормализации выходит за ``dest``, не записывается.
    Такой член пропускается, распаковка остальных продолжается.
    ``..``, который остаётся внутри ``dest``, схлопывается в безопасный
    относительный путь и не ведёт наружу.

    Результат — пути извлечённых изображений в естественном порядке.
    Повреждённый архив поднимает ошибку ``zipfile`` как есть.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            target = _safe_member_target(dest, dest_root, info.filename)
            if target is None or not is_image(target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    unique = list(dict.fromkeys(extracted))
    unique.sort(key=lambda path: natural_sort_key(path.relative_to(dest).as_posix()))
    return unique


def plan_chapters(
    paths: Sequence[Path],
    mode: str,
    *,
    root: Path | None = None,
    archive_stem: str | None = None,
) -> list[tuple[Path, str]]:
    """Назначить главу каждому пути. Порядок входа не меняется.

    Режим ``flat`` и любой другой, кроме ``subdir``: глава всегда ``""``,
    в том числе когда передан ``archive_stem``.

    Режим ``subdir`` без ``root``: первую папку посчитать нельзя, у всех ``""``.

    Режим ``subdir`` для обычной папки (``archive_stem is None``): глава —
    имя первой папки в ``path.relative_to(root)``. Файл прямо в ``root``
    получает ``""``. Вложенные уровни глубже первой папки в главу не входят.

    Режим ``subdir`` для распакованного архива (``root`` — каталог
    извлечения, ``archive_stem`` задан):

    - если у каждого изображения одна и та же первая папка под ``root``,
      глава — имя этой папки, а не stem архива;
    - иначе если все изображения лежат прямо в ``root`` (подпапки в путях
      нет), глава — ``archive_stem``;
    - иначе у файла глава — его первая папка под ``root``, а файл прямо
      в ``root`` получает ``""``.

    Путь вне ``root`` получает ``""`` и не считается файлом в корне, когда
    выбирается stem архива.
    """
    items = [Path(path) for path in paths]
    if mode != "subdir" or root is None:
        return [(path, "") for path in items]

    root_path = Path(root)
    places = [_place_under_root(path, root_path) for path in items]
    if archive_stem is not None and items and len(set(places)) == 1:
        only = places[0]
        if only is None:
            return [(path, archive_stem) for path in items]
        if isinstance(only, str):
            return [(path, only) for path in items]

    chapters: list[tuple[Path, str]] = []
    for path, place in zip(items, places):
        chapter = place if isinstance(place, str) else ""
        chapters.append((path, chapter))
    return chapters


def _place_under_root(path: Path, root: Path) -> str | None | object:
    """Первая папка под ``root``, ``None`` в корне, ``_OUTSIDE`` вне корня."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return _OUTSIDE
    if len(relative.parts) >= 2:
        return relative.parts[0]
    return None


def _relative_parts(member: str) -> tuple[str, ...] | None:
    """Части пути члена архива внутри каталога назначения.

    ``None`` — путь писать нельзя: абсолютный, диск, UNC или ``..`` наружу.
    """
    if not member or "\x00" in member:
        return None
    if member.endswith("/") or member.endswith("\\"):
        return None
    windows = PureWindowsPath(member)
    if windows.is_absolute() or windows.drive or windows.root:
        return None
    normalized = member.replace("\\", "/")
    if normalized.startswith("/"):
        return None
    posix = PurePosixPath(normalized)
    if posix.is_absolute():
        return None
    safe: list[str] = []
    for part in posix.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not safe:
                return None
            safe.pop()
            continue
        if ":" in part or "/" in part or "\\" in part:
            return None
        safe.append(part)
    if not safe:
        return None
    return tuple(safe)


def _safe_member_target(dest: Path, dest_root: Path, member: str) -> Path | None:
    """Путь члена под ``dest`` либо ``None``, если запись вышла бы наружу."""
    parts = _relative_parts(member)
    if parts is None:
        return None
    logical = dest.joinpath(*parts)
    try:
        logical.resolve().relative_to(dest_root)
    except (ValueError, OSError):
        return None
    return logical
