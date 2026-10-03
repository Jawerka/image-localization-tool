"""Экспорт страниц в папку пользователя или в архив ZIP/CBZ.

Можно сохранить перевод (``result.png``), очищенную страницу (``clean.png``)
или оба файла. Оригиналы картинок не перезаписываются.
Кадры в архиве пишутся методом ``ZIP_STORED`` (без deflate).
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import NamedTuple

from PIL import Image

from src.app.store import ProjectStore

_CONTENT = frozenset({"result", "clean", "both"})
_READY = frozenset({"done", "ready"})
_NOT_READY_REASON = "не готова"
_NOT_FOUND_REASON = "страница не найдена"
_ARCHIVE_SUFFIX = {"zip": ".zip", "cbz": ".cbz"}


class ExportResult(NamedTuple):
    """Успешно записанные файлы и сообщения о пропущенных страницах."""

    paths: list[Path]
    errors: list[str]


class ArchiveExportResult(NamedTuple):
    """Созданный архив и страницы, которые в него не попали.

    ``paths`` — записанные архивы. Пустой список, если не упакован ни один кадр:
    пустой файл архива при этом не создаётся.
    ``skipped`` — словари ``id``, ``name``, ``reason``.
    ``errors`` — пропавшие файлы и неизвестные страницы теми же фразами, что у
    ``export_pages``. Причина ``не готова`` пишется только в ``skipped``.
    """

    paths: list[Path]
    skipped: list[dict]
    errors: list[str]


def export_pages(
    store: ProjectStore,
    project_id: str,
    page_ids: list[str],
    dest: Path,
    fmt: str,
    jpeg_quality: int,
    conflict: str,
    content: str = "result",
) -> ExportResult:
    """Скопировать кадры страниц в ``dest``.

    ``content``: ``result`` (перевод), ``clean`` (ретушь после маски) или ``both``.
    Неизвестное значение трактуется как ``result``. При ``both`` очищенная
    копия получает суффикс ``-clean``. Имя файла — имя оригинала.
    ``rename`` даёт ``name-2.ext``, если имя занято. Нет нужного файла —
    страница попадает в ``errors``, остальные продолжаются.
    """
    destination = Path(dest)
    if destination.exists() and not destination.is_dir():
        return ExportResult([], [f"Папка экспорта не является каталогом: {destination}"])
    destination.mkdir(parents=True, exist_ok=True)

    kind = str(content or "result").lower()
    if kind not in _CONTENT:
        kind = "result"

    project = store.open_project(project_id)
    by_id = {str(page.get("id") or ""): page for page in project.get("pages") or []}
    protected = {
        _norm(page.get("source_path"))
        for page in by_id.values()
        if page.get("source_path")
    }
    extension = ".jpg" if str(fmt).lower() in ("jpg", "jpeg") else ".png"
    quality = max(1, min(100, int(jpeg_quality)))
    policy = str(conflict or "rename").lower()
    if policy not in ("rename", "overwrite", "skip"):
        policy = "rename"

    written: list[Path] = []
    errors: list[str] = []
    for page_id in page_ids:
        page = by_id.get(str(page_id))
        if page is None:
            errors.append(f"{page_id}: страница не найдена")
            continue
        label = page.get("name") or page_id
        stem = Path(str(page.get("source_path") or page.get("name") or page_id)).stem
        outputs = _outputs_for(kind)
        sources: list[tuple[Path, str]] = []
        missing = False
        for image_kind, suffix in outputs:
            source = store.image_path(project_id, str(page_id), image_kind)
            if not source.is_file():
                filename = "clean.png" if image_kind == "clean" else "result.png"
                errors.append(f"{label}: нет {filename}")
                missing = True
                break
            sources.append((source, suffix))
        if missing:
            continue
        for source, suffix in sources:
            target = _pick_destination(
                destination, f"{stem}{suffix}", extension, policy, protected,
            )
            if target is None:
                continue
            _save_result(source, target, extension, quality)
            written.append(target)
    return ExportResult(written, errors)


def export_archive(
    store: ProjectStore,
    project_id: str,
    page_ids: list[str],
    dest: Path,
    *,
    archive: str = "cbz",
    fmt: str = "png",
    jpeg_quality: int = 90,
    content: str = "result",
    name_template: str = "{chapter}/{index:03}_{stem}",
    only_ready: bool = False,
) -> ArchiveExportResult:
    """Упаковать кадры страниц в ZIP или CBZ.

    ``archive`` — ``cbz`` или ``zip`` (оба являются zip). Суффикс следует типу:
    нет суффикса — дописывается ``.cbz`` или ``.zip``; уже верный — путь
    сохраняется; противоположный ``.zip``/``.cbz`` заменяется. Неизвестный
    тип трактуется как ``cbz``.

    ``content`` как у ``export_pages``: ``result``, ``clean`` или ``both``
    (неизвестное значение — ``result``). Кадры выбирает ``_outputs_for``.
    При ``both`` второй член — тот же путь с ``-clean`` перед расширением.
    Нет хотя бы одного нужного файла — страница целиком не пишется.

    ``name_template`` форматируется полями ``chapter``, ``index`` (int),
    ``stem``, ``name``. ``{index:03}`` — обычный формат Python. ``index`` —
    номер с 1 среди страниц из ``page_ids``, которые прошли ``only_ready``
    и реально записаны, в порядке ``page_ids``, без дыр. ``stem`` — stem
    оригинала, ``name`` — имя файла оригинала. Расширение ``fmt`` (``.png``
    или ``.jpg``) дописывается к последнему сегменту.

    Пустая глава (нет ключа ``chapter`` или строка пустая) не даёт ведущего
    слэша и пустого сегмента: ``{chapter}/{index:03}_{stem}`` → ``001_page.png``,
    с главой ``vol1`` → ``vol1/001_page.png``. Вложенный ``chapter`` сохраняет
    подпапки. Сегменты ``..``, ``.`` и префикс диска (``C:``) выбрасываются
    и не поднимают путь вверх.

    ``only_ready``: статус не ``done`` и не ``ready`` — страница не пишется,
    ``reason`` ровно ``не готова``. Статус берётся из записи страницы проекта;
    если ключа ``status`` нет — из ``store.page_status``. По умолчанию фильтр
    выключен.

    Если не записан ни один кадр, архив не создаётся (``paths`` пуст), уже
    лежащий по пути файл не затирается. Пропавший кадр: ``skipped.reason``
    ``нет result.png`` или ``нет clean.png`` и та же фраза в ``errors`` после
    имени, как у ``export_pages``. Неизвестная страница: ``страница не найдена``
    и в ``skipped``, и в ``errors``.
    """
    destination = _archive_destination(dest, archive)
    kind = str(content or "result").lower()
    if kind not in _CONTENT:
        kind = "result"
    extension = ".jpg" if str(fmt).lower() in ("jpg", "jpeg") else ".png"
    quality = max(1, min(100, int(jpeg_quality)))
    template = name_template or "{chapter}/{index:03}_{stem}"
    outputs = _outputs_for(kind)

    project = store.open_project(project_id)
    by_id = {str(page.get("id") or ""): page for page in project.get("pages") or []}

    planned: list[tuple[str, Path]] = []
    skipped: list[dict] = []
    errors: list[str] = []
    packed = 0
    for page_id in page_ids:
        page = by_id.get(str(page_id))
        if page is None:
            skipped.append(_skip(page_id, page_id, _NOT_FOUND_REASON))
            errors.append(f"{page_id}: {_NOT_FOUND_REASON}")
            continue
        label = page.get("name") or page_id
        if only_ready and _export_status(store, project_id, page).casefold() not in _READY:
            skipped.append(_skip(page.get("id") or page_id, label, _NOT_READY_REASON))
            continue
        sources, missing_name = _page_sources(store, project_id, page, page_id, outputs)
        if missing_name is not None:
            errors.append(f"{label}: нет {missing_name}")
            skipped.append(_skip(page.get("id") or page_id, label, f"нет {missing_name}"))
            continue
        packed += 1
        stem = Path(str(page.get("source_path") or page.get("name") or page_id)).stem
        name = str(page.get("name") or stem)
        chapter = "" if page.get("chapter") is None else str(page.get("chapter")).strip()
        for source, suffix in sources:
            arcname = _arc_member(
                template,
                chapter=chapter,
                index=packed,
                stem=stem,
                name=name,
                suffix=suffix,
                extension=extension,
            )
            planned.append((arcname, source))

    if not planned:
        return ArchiveExportResult([], skipped, errors)
    if destination.exists() and destination.is_dir():
        errors.append(f"Путь архива является каталогом: {destination}")
        return ArchiveExportResult([], skipped, errors)

    payloads = [
        (arcname, _encode_image(source, extension, quality))
        for arcname, source in planned
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive_file:
        for arcname, payload in payloads:
            info = zipfile.ZipInfo(arcname)
            info.compress_type = zipfile.ZIP_STORED
            info.flag_bits |= 0x800
            info.external_attr = 0o644 << 16
            archive_file.writestr(info, payload, compress_type=zipfile.ZIP_STORED)
    return ArchiveExportResult([destination], skipped, errors)


def _outputs_for(kind: str) -> list[tuple[str, str]]:
    if kind == "clean":
        return [("clean", "")]
    if kind == "both":
        return [("result", ""), ("clean", "-clean")]
    return [("result", "")]


def _encode_image(source: Path, extension: str, quality: int) -> bytes:
    """Перевести кадр в PNG или JPEG. Та же цветовая логика, что у папочного экспорта."""
    buffer = io.BytesIO()
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        if extension == ".jpg":
            rgb.save(buffer, "JPEG", quality=quality)
        else:
            rgb.save(buffer, "PNG")
    return buffer.getvalue()


def _save_result(source: Path, target: Path, extension: str, quality: int) -> None:
    target.write_bytes(_encode_image(source, extension, quality))


def _skip(page_id: object, name: object, reason: str) -> dict:
    return {"id": str(page_id), "name": str(name), "reason": reason}


def _export_status(store: ProjectStore, project_id: str, page: dict) -> str:
    """Статус из записи проекта, иначе из ``page.json`` через хранилище."""
    if "status" in page and page.get("status") is not None:
        return str(page.get("status") or "").strip()
    page_id = str(page.get("id") or "")
    try:
        payload = store.page_status(project_id, page_id)
    except (FileNotFoundError, OSError, ValueError):
        return ""
    return str(payload.get("status") or "").strip()


def _page_sources(
    store: ProjectStore,
    project_id: str,
    page: dict,
    page_id: str,
    outputs: list[tuple[str, str]],
) -> tuple[list[tuple[Path, str]], str | None]:
    """Источники кадров. Второе значение — имя отсутствующего файла."""
    sources: list[tuple[Path, str]] = []
    for image_kind, suffix in outputs:
        source = store.image_path(project_id, str(page.get("id") or page_id), image_kind)
        if not source.is_file():
            filename = "clean.png" if image_kind == "clean" else "result.png"
            return [], filename
        sources.append((source, suffix))
    return sources, None


def _archive_destination(dest: Path, archive: str) -> Path:
    kind = str(archive or "cbz").strip().lower()
    if kind not in _ARCHIVE_SUFFIX:
        kind = "cbz"
    suffix = _ARCHIVE_SUFFIX[kind]
    path = Path(dest)
    current = path.suffix.lower()
    if current == suffix:
        return path
    if current in _ARCHIVE_SUFFIX.values():
        return path.with_suffix(suffix)
    if current:
        return Path(str(path) + suffix)
    return path.with_suffix(suffix)


def _arc_member(
    template: str,
    *,
    chapter: str,
    index: int,
    stem: str,
    name: str,
    suffix: str,
    extension: str,
) -> str:
    """Имя члена архива без выхода за его пространство имён."""
    values = {
        "chapter": _plain(chapter),
        "index": index,
        "stem": _plain(stem),
        "name": _plain(name),
    }
    try:
        rendered = str(template).format(**values)
    except (KeyError, ValueError, IndexError):
        rendered = f"{index:03}_{_plain(stem)}"
    parts = _safe_parts(rendered)
    if not parts:
        parts = _safe_parts(f"{index:03}_{_plain(stem)}") or [f"{index:03}_page"]
    parts[-1] = f"{parts[-1]}{suffix}{extension}"
    return "/".join(parts)


def _plain(value: str) -> str:
    return str(value or "").replace("{", "").replace("}", "")


def _safe_parts(rendered: str) -> list[str]:
    """Сегменты пути архива: без пустых, ``..`` и буквы диска."""
    parts: list[str] = []
    for raw in re.split(r"[\\/]+", str(rendered)):
        part = raw.replace("\x00", "").strip()
        if len(part) >= 2 and part[0].isalpha() and part[1] == ":":
            part = part[2:].strip()
        if not part or part in (".", ".."):
            continue
        parts.append(part)
    return parts


def _pick_destination(
    directory: Path,
    stem: str,
    extension: str,
    conflict: str,
    protected: set[str],
) -> Path | None:
    first = directory / f"{stem}{extension}"
    protected_hit = _norm(first) in protected
    if not first.exists() and not protected_hit:
        return first
    if conflict == "skip":
        return None
    if conflict == "overwrite" and first.exists() and not protected_hit:
        return first
    number = 2
    while number < 10000:
        candidate = directory / f"{stem}-{number}{extension}"
        if not candidate.exists() and _norm(candidate) not in protected:
            return candidate
        number += 1
    return None


def _norm(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))
