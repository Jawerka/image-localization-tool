"""Импорт изображений: список файлов, распаковка архива и план глав.

Чистые функции без хранилища и без моделей. Типичный вызов:

- папка: ``list_images(root, recursive)``, затем
  ``plan_chapters(paths, mode, root=root)``;
- архив: ``extract_archive(archive, dest)``, затем
  ``plan_chapters(paths, mode, root=dest, archive_stem=archive.stem)``.

Архивы: zip, cbz, cbr, rar, cb7, 7z, cbt, tar. Формат берётся по содержимому,
суффикс — только запасной вариант: многие ``.cbr`` на деле являются zip.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
ARCHIVE_SUFFIXES = frozenset({
    ".zip", ".cbz", ".cbr", ".rar", ".cb7", ".7z", ".cbt", ".tar",
})
# Папок над файлом не больше этого числа. ``a/b/c/d/e/page.png`` — пятый уровень.
MAX_ARCHIVE_DEPTH = 5

_SUFFIX_KIND = {
    ".zip": "zip",
    ".cbz": "zip",
    ".rar": "rar",
    ".cbr": "rar",
    ".7z": "7z",
    ".cb7": "7z",
    ".tar": "tar",
    ".cbt": "tar",
}

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
    """Суффикс zip, cbz, cbr, rar, cb7, 7z, cbt или tar. Содержимое не проверяется."""
    return Path(path).suffix.casefold() in ARCHIVE_SUFFIXES


class NoImagesError(ValueError):
    """В архиве нет изображений на допустимой глубине."""


def archive_images(archive: Path) -> list[str]:
    """Имена изображений в архиве без распаковки.

    Берутся png, jpg, jpeg, bmp, tif и tiff не глубже ``MAX_ARCHIVE_DEPTH``
    папок. Файлы с ``-mask`` в имени и небезопасные пути пропускаются.
    Пустой результат — ``NoImagesError``.
    """
    archive = Path(archive)
    with _open_reader(archive) as reader:
        names = _select_image_members(reader.file_names())
    if not names:
        raise _no_images(archive)
    return names


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
    """Извлечь изображения из архива в ``dest``.

    Подходят zip, cbz, cbr, rar, cb7, 7z, cbt и tar. Формат определяется
    по содержимому. Записи-каталоги, ссылки и не-изображения пропускаются.
    Файлы глубже ``MAX_ARCHIVE_DEPTH`` папок не читаются. Имена с ``-mask``
    тоже пропускаются. Безопасный относительный путь внутри архива
    сохраняется, поэтому папка главы не теряется. ``dest`` создаётся,
    только если есть что извлекать.

    Zip-slip: член с абсолютным путём, префиксом диска, UNC или ``..``,
    который после нормализации выходит за ``dest``, не записывается.
    Такой член пропускается, распаковка остальных продолжается.
    ``..``, который остаётся внутри ``dest``, схлопывается в безопасный
    относительный путь и не ведёт наружу.

    Результат — пути извлечённых изображений в естественном порядке.
    Если подходящих изображений нет — ``NoImagesError``.
    Повреждённый архив поднимает ошибку формата как есть.
    """
    archive = Path(archive)
    dest = Path(dest)
    extracted: list[Path] = []
    with _open_reader(archive) as reader:
        names = _select_image_members(reader.file_names())
        if not names:
            raise _no_images(archive)
        dest.mkdir(parents=True, exist_ok=True)
        dest_root = dest.resolve()
        for name in names:
            target = _safe_member_target(dest, dest_root, name)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with reader.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    unique = list(dict.fromkeys(extracted))
    unique.sort(key=lambda path: natural_sort_key(path.relative_to(dest).as_posix()))
    if not unique:
        raise _no_images(archive)
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


def _no_images(archive: Path) -> NoImagesError:
    return NoImagesError(
        f"В архиве «{Path(archive).name}» нет изображений — переводить нечего"
    )


def _select_image_members(names: Sequence[str]) -> list[str]:
    """Имена членов-изображений: безопасный путь, глубина и без ``-mask``."""
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        parts = _relative_parts(name)
        if parts is None or len(parts) - 1 > MAX_ARCHIVE_DEPTH:
            continue
        leaf = Path(parts[-1])
        if not is_image(leaf) or "-mask" in leaf.stem.casefold():
            continue
        key = "/".join(parts)
        if key in seen:
            continue
        seen.add(key)
        chosen.append((key, name))
    chosen.sort(key=lambda item: natural_sort_key(item[0]))
    return [name for _, name in chosen]


def _detect_kind(path: Path) -> str:
    """zip, rar, 7z или tar. Сначала содержимое, потом суффикс."""
    if zipfile.is_zipfile(path):
        return "zip"
    if _probe_rar(path):
        return "rar"
    if _probe_7z(path):
        return "7z"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, tarfile.TarError):
        pass
    kind = _SUFFIX_KIND.get(path.suffix.casefold())
    if kind:
        return kind
    raise ValueError(f"Неизвестный архив: {path.name}")


def _probe_rar(path: Path) -> bool:
    try:
        import rarfile
    except ImportError:
        return False
    try:
        return bool(rarfile.is_rarfile(path))
    except (OSError, ValueError):
        return False


def _probe_7z(path: Path) -> bool:
    try:
        import py7zr
    except ImportError:
        return False
    try:
        return bool(py7zr.is_7zfile(path))
    except (OSError, ValueError):
        return False


def _open_reader(archive: Path):
    kind = _detect_kind(archive)
    if kind == "zip":
        return _ZipReader(archive)
    if kind == "rar":
        return _RarReader(archive)
    if kind == "7z":
        return _SevenReader(archive)
    if kind == "tar":
        return _TarReader(archive)
    raise ValueError(f"Неизвестный архив: {archive.name}")


class _Closable:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _ZipReader(_Closable):
    def __init__(self, path: Path):
        self._bundle = zipfile.ZipFile(path)

    def file_names(self) -> list[str]:
        return [info.filename for info in self._bundle.infolist() if not info.is_dir()]

    def open(self, name: str):
        return self._bundle.open(name, "r")

    def close(self) -> None:
        self._bundle.close()


class _TarReader(_Closable):
    def __init__(self, path: Path):
        self._bundle = tarfile.open(path, "r:*")

    def file_names(self) -> list[str]:
        return [member.name for member in self._bundle.getmembers() if member.isfile()]

    def open(self, name: str):
        member = self._bundle.getmember(name)
        if not member.isfile():
            raise ValueError(f"Не файл: {name}")
        handle = self._bundle.extractfile(member)
        if handle is None:
            raise ValueError(f"Не удалось прочитать {name}")
        return handle

    def close(self) -> None:
        self._bundle.close()


def _find_unpack_tool() -> tuple[str | None, str | None]:
    """Пути unrar и 7z, если они есть на машине."""
    unrar = shutil.which("unrar")
    seven = shutil.which("7z") or shutil.which("7za")
    if seven is None:
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if not root:
                continue
            candidate = Path(root) / "7-Zip" / "7z.exe"
            if candidate.is_file():
                seven = str(candidate)
                break
    return unrar, seven


def _bind_rar_tool(module) -> None:
    """Подсказать rarfile, где лежит unrar или 7-Zip."""
    unrar, seven = _find_unpack_tool()
    if unrar:
        module.UNRAR_TOOL = unrar
    if seven:
        module.SEVENZIP_TOOL = seven
        if hasattr(module, "SEVENZIP2_TOOL"):
            module.SEVENZIP2_TOOL = seven
    if unrar or seven:
        module.tool_setup(force=True)


class _RarReader(_Closable):
    def __init__(self, path: Path):
        try:
            import rarfile
        except ImportError as exc:
            raise ValueError("Для CBR/RAR нужен пакет rarfile") from exc
        _bind_rar_tool(rarfile)
        try:
            self._bundle = rarfile.RarFile(path)
        except rarfile.RarCannotExec as exc:
            raise ValueError("Для CBR/RAR нужен 7-Zip или UnRAR") from exc
        self._rarfile = rarfile

    def file_names(self) -> list[str]:
        return [info.filename for info in self._bundle.infolist() if not info.isdir()]

    def open(self, name: str):
        try:
            return self._bundle.open(name)
        except self._rarfile.RarCannotExec as exc:
            raise ValueError("Для CBR/RAR нужен 7-Zip или UnRAR") from exc

    def close(self) -> None:
        self._bundle.close()


class _SevenReader(_Closable):
    def __init__(self, path: Path):
        try:
            import py7zr
        except ImportError as exc:
            raise ValueError("Для CB7/7Z нужен пакет py7zr") from exc
        self._py7zr = py7zr
        self._bundle = py7zr.SevenZipFile(path, mode="r")

    def file_names(self) -> list[str]:
        names = [
            info.filename
            for info in self._bundle.list()
            if not info.is_directory
        ]
        self._bundle.reset()
        return names

    def open(self, name: str):
        factory = self._memory_factory()
        self._bundle.extract(targets=[name], factory=factory)
        self._bundle.reset()
        buffer = factory.files.get(name)
        if buffer is None and len(factory.files) == 1:
            buffer = next(iter(factory.files.values()))
        if buffer is None:
            raise ValueError(f"Не удалось прочитать {name}")
        buffer.seek(0)
        return buffer

    def _memory_factory(self):
        py7zr = self._py7zr

        class _Kept(io.BytesIO):
            """py7zr закрывает поток после записи, а читаем мы его следом."""

            def close(self) -> None:
                return None

        class _MemoryFactory(py7zr.WriterFactory):
            def __init__(self):
                self.files: dict[str, io.BytesIO] = {}

            def create(self, filename: str) -> io.BytesIO:
                buffer = _Kept()
                self.files[filename] = buffer
                return buffer

        return _MemoryFactory()

    def close(self) -> None:
        self._bundle.close()


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
