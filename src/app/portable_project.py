"""Портативный пакет проекта ``.ilt.zip``.

``pages/`` — только исходники; ``res/`` — mask, clean, result, thumb.
``schema_version`` 1 — только pages + JSON; 2 — ещё ``res/``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from src.app.store import ProjectStore

KIND = "ilt-project"
SCHEMA_VERSION = 2
_PREFIX_RE = re.compile(r"^(\d{4})_(.+)$")
_SAFE_NAME_RE = re.compile(r"[^\w.\-]+", re.UNICODE)

# kind в JSON → (имя в store, суффикс файла в res/ относительно 0001_name без .ext)
_ARTIFACTS = (
    ("mask", "mask", ".mask.png"),
    ("clean", "clean", ".clean.png"),
    ("result", "result", ".result.png"),
    ("thumb", "thumb", ".thumb.jpg"),
)


class PortableProjectError(ValueError):
    """Ошибка формата или содержимого портативного пакета."""


@dataclass
class PackResult:
    path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass
class UnpackResult:
    project: dict
    warnings: list[str] = field(default_factory=list)
    editor: dict | None = None


def normalize_editor(raw: object) -> dict | None:
    """Сессия UI: active_page_id, zoom, scroll_left, scroll_top."""
    if not isinstance(raw, dict):
        return None
    active = str(raw.get("active_page_id") or raw.get("activePageId") or "").strip()
    zoom = raw.get("zoom")
    if zoom not in ("fit", "fit-width"):
        try:
            zoom_num = float(zoom)
            zoom = zoom_num if zoom_num > 0 else "fit"
        except (TypeError, ValueError):
            zoom = "fit"
    try:
        scroll_left = max(0.0, float(raw.get("scroll_left", raw.get("scrollLeft", 0)) or 0))
    except (TypeError, ValueError):
        scroll_left = 0.0
    try:
        scroll_top = max(0.0, float(raw.get("scroll_top", raw.get("scrollTop", 0)) or 0))
    except (TypeError, ValueError):
        scroll_top = 0.0
    return {
        "active_page_id": active,
        "zoom": zoom,
        "scroll_left": scroll_left,
        "scroll_top": scroll_top,
    }


def pack_project(
    store: ProjectStore,
    project_id: str,
    dest: Path,
    *,
    editor: dict | None = None,
) -> PackResult:
    """Собрать ZIP по текущему порядку страниц. Ошибки полей не прерывают весь Save."""
    project = store.open_project(project_id)
    pages = [item for item in project.get("pages") or [] if isinstance(item, dict)]
    if not pages:
        raise PortableProjectError("Нет страниц для сохранения")

    dest = Path(dest)
    if not str(dest.name).lower().endswith(".zip"):
        dest = dest.with_name(dest.name + ".ilt.zip")

    warnings: list[str] = []
    manifest_pages: list[dict] = []
    files_to_write: list[tuple[Path, str]] = []

    for index, record in enumerate(pages, start=1):
        page_id = str(record.get("id") or "")
        label = str(record.get("name") or page_id or f"#{index}")
        if not page_id:
            warnings.append(f"{label}: нет id страницы")
            continue

        original_name = _original_name(str(record.get("name") or "page.png"))
        packed_name = f"{index:04d}_{original_name}"
        stem = Path(packed_name).stem
        image_rel = f"pages/{packed_name}"
        errors: list[str] = []

        source = Path(str(record.get("source_path") or ""))
        image_ok = False
        try:
            if source.is_file():
                files_to_write.append((source, image_rel))
                image_ok = True
            else:
                errors.append("image: нет исходного файла")
        except OSError as exc:
            errors.append(f"image: {exc}")

        if not image_ok:
            warnings.append(f"{label}: {errors[-1] if errors else 'нет image'}")
            continue

        try:
            status = store.page_status(project_id, page_id)
            page_status = status.get("status") or "idle"
        except (FileNotFoundError, ValueError, OSError) as exc:
            page_status = "idle"
            errors.append(f"status: {exc}")

        document = None
        try:
            document = store.read_document(project_id, page_id).to_dict()
        except (FileNotFoundError, ValueError, OSError) as exc:
            errors.append(f"document: {exc}")

        entry: dict = {
            "id": page_id,
            "name": original_name,
            "status": page_status,
            "chapter": str(record.get("chapter") or ""),
            "image": image_rel,
            "document": document,
            "mask": None,
            "clean": None,
            "result": None,
            "thumb": None,
            "errors": errors,
        }

        for json_key, store_kind, suffix in _ARTIFACTS:
            try:
                path = store.image_path(project_id, page_id, store_kind)
                if not path.is_file():
                    entry[json_key] = None
                    continue
                rel = f"res/{stem}{suffix}"
                files_to_write.append((path, rel))
                entry[json_key] = rel
            except (ValueError, OSError) as exc:
                entry[json_key] = None
                errors.append(f"{json_key}: {exc}")

        if errors:
            for item in errors:
                warnings.append(f"{label}: {item}")
        manifest_pages.append(entry)

    if not manifest_pages:
        raise PortableProjectError("Не удалось включить ни одной страницы в пакет")

    manifest = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "name": str(project.get("name") or "Проект"),
        "source_lang": str(project.get("source_lang") or "auto"),
        "target_lang": str(project.get("target_lang") or "ru"),
        "pages": [
            {
                "id": item["id"],
                "name": item["name"],
                "status": item["status"],
                "chapter": item["chapter"],
                "image": item["image"],
                "document": item["document"],
                "mask": item["mask"],
                "clean": item["clean"],
                "result": item["result"],
                "thumb": item["thumb"],
                "errors": item["errors"],
            }
            for item in manifest_pages
        ],
    }
    editor_payload = normalize_editor(editor)
    if editor_payload is not None:
        manifest["editor"] = editor_payload
    glossary = project.get("glossary")
    if isinstance(glossary, list):
        manifest["glossary"] = glossary
    styles = project.get("styles")
    if isinstance(styles, list):
        manifest["styles"] = styles

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "project.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for source, arcname in files_to_write:
                try:
                    archive.write(source, arcname=arcname)
                except OSError as exc:
                    warnings.append(f"{arcname}: {exc}")
        if dest.exists():
            dest.unlink()
        temporary.replace(dest)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return PackResult(path=dest, warnings=warnings)


def is_portable_package(path: Path) -> bool:
    """ZIP с валидным корневым project.json (ilt-project). Без распаковки."""
    try:
        return resolve_archive_open_kind(path) == "portable"
    except PortableProjectError:
        return False


def resolve_archive_open_kind(path: Path) -> Literal["chapter", "portable"]:
    """Как открыть ZIP: глава или портативный проект.

    Явный ``kind: ilt-project`` с битым manifest — ошибка, не ingest.
    """
    path = Path(path)
    if not path.is_file() or not zipfile.is_zipfile(path):
        return "chapter"
    with zipfile.ZipFile(path, "r") as archive:
        key = _project_json_member(set(archive.namelist()))
        if key is None:
            return "chapter"
        try:
            manifest = json.loads(archive.read(key).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PortableProjectError("Повреждённый project.json") from exc
        if not isinstance(manifest, dict):
            return "chapter"
        if str(manifest.get("kind") or "") != KIND:
            return "chapter"
        _validate_manifest(manifest)
        return "portable"


def unpack_project(store: ProjectStore, package: Path) -> UnpackResult:
    """Загрузить пакет в новый проект. Частичные сбои — в warnings."""
    package = Path(package)
    if not package.is_file():
        raise PortableProjectError(f"Файл не найден: {package}")

    warnings: list[str] = []
    with zipfile.ZipFile(package, "r") as archive:
        names = set(archive.namelist())
        if "project.json" not in names:
            raise PortableProjectError("В архиве нет project.json — это не портативный проект")
        try:
            manifest = json.loads(archive.read("project.json").decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PortableProjectError("Повреждённый project.json") from exc
        raw_pages = _validate_manifest(manifest)

        staging = Path(tempfile.mkdtemp(prefix="ilt-package-"))
        created_id: str | None = None
        imported = 0
        try:
            project = store.create_project(
                str(manifest.get("name") or package.stem),
                str(manifest.get("source_lang") or "auto"),
                str(manifest.get("target_lang") or "ru"),
            )
            created_id = str(project["id"])
            import_dir = store.project_dir(created_id) / "imports" / _safe_stem(package.stem)
            import_dir.mkdir(parents=True, exist_ok=True)

            for entry in raw_pages:
                label = str(entry.get("name") or entry.get("id") or "?")
                image = str(entry.get("image") or "").replace("\\", "/").lstrip("/")
                if not image:
                    warnings.append(f"{label}: нет image в JSON")
                    continue
                if image not in names:
                    warnings.append(f"{label}: в архиве нет {image}")
                    continue
                source_name = Path(image).name
                try:
                    staged = staging / source_name
                    with archive.open(image) as src, staged.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    dest_image = import_dir / source_name
                    shutil.copy2(staged, dest_image)
                except OSError as exc:
                    warnings.append(f"{label}: image: {exc}")
                    continue

                document = entry.get("document") if isinstance(entry.get("document"), dict) else None
                if document is None and entry.get("document") is not None:
                    warnings.append(f"{label}: document повреждён, пропущен")

                record = store.append_portable_page(
                    created_id,
                    dest_image,
                    page_id=str(entry.get("id") or "") or None,
                    name=str(entry.get("name") or _original_name(source_name)),
                    chapter=str(entry.get("chapter") or ""),
                    status=str(entry.get("status") or "idle"),
                    document=document,
                )
                page_id = str(record.get("id") or "")
                imported += 1

                artifact_paths: dict[str, Path] = {}
                for json_key, _store_kind, _suffix in _ARTIFACTS:
                    rel = entry.get(json_key)
                    if not isinstance(rel, str) or not rel.strip():
                        continue
                    rel = rel.replace("\\", "/").lstrip("/")
                    if rel not in names:
                        warnings.append(f"{label}: в архиве нет {rel}")
                        continue
                    try:
                        staged_art = staging / rel.replace("/", "_")
                        with archive.open(rel) as src, staged_art.open("wb") as out:
                            shutil.copyfileobj(src, out)
                        artifact_paths[json_key] = staged_art
                    except OSError as exc:
                        warnings.append(f"{label}: {json_key}: {exc}")

                if artifact_paths:
                    warnings.extend(
                        store.restore_portable_artifacts(created_id, page_id, artifact_paths)
                    )

            if imported == 0:
                raise PortableProjectError("Не удалось импортировать ни одной страницы")

            if isinstance(manifest.get("glossary"), list):
                try:
                    store.write_glossary(created_id, manifest["glossary"])
                except (ValueError, OSError) as exc:
                    warnings.append(f"glossary: {exc}")
            if isinstance(manifest.get("styles"), list):
                try:
                    store.write_styles(created_id, manifest["styles"])
                except (ValueError, OSError) as exc:
                    warnings.append(f"styles: {exc}")

            editor_payload = normalize_editor(manifest.get("editor"))
            return UnpackResult(
                project=store.open_project(created_id),
                warnings=warnings,
                editor=editor_payload,
            )
        except Exception:
            if created_id is not None:
                shutil.rmtree(store.project_dir(created_id), ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _project_json_member(names: set[str]) -> str | None:
    for name in names:
        norm = name.replace("\\", "/").lstrip("./")
        if norm == "project.json":
            return name
    return None


def _validate_manifest(manifest: dict) -> list[dict]:
    if not isinstance(manifest, dict):
        raise PortableProjectError("project.json должен быть объектом")
    if str(manifest.get("kind") or "") != KIND:
        raise PortableProjectError('Ожидался kind "ilt-project"')
    version = manifest.get("schema_version")
    if version is None:
        raise PortableProjectError("Нет schema_version")
    try:
        if int(version) < 1:
            raise PortableProjectError("Некорректный schema_version")
    except (TypeError, ValueError) as exc:
        raise PortableProjectError("Некорректный schema_version") from exc

    raw_pages = manifest.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise PortableProjectError("В проекте нет страниц")

    pages: list[dict] = []
    for item in raw_pages:
        if not isinstance(item, dict):
            raise PortableProjectError("Элемент pages должен быть объектом")
        pages.append(dict(item))
    return pages


def _original_name(name: str) -> str:
    text = Path(str(name or "page.png")).name
    match = _PREFIX_RE.match(text)
    if match:
        return match.group(2)
    return text or "page.png"


def _safe_stem(stem: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(stem)).strip("._")
    return cleaned or "package"
