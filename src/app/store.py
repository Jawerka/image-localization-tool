"""Проекты и страницы на диске.

Оригинал картинки не копируется: в проекте хранится абсолютный ``source_path``.
Модели и пайплайн здесь не импортируются.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from src.app.document import PageDocument
from src.app.glossary import glossary_from_pages, normalize_glossary
from src.app.ingest import extract_archive, is_archive, is_image, list_images, plan_chapters

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_NUMBER_RE = re.compile(r"(\d+)")
_STATUSES = {"idle", "queued", "running", "done", "edited", "offline", "error"}
_IMAGE_NAMES = {
    "mask": "mask_auto.png",
    "clean": "clean.png",
    "result": "result.png",
    "thumb": "thumb.jpg",
}


class VersionConflict(Exception):
    """Документ на диске новее, чем ``base_version`` у правки."""

    def __init__(self, document: PageDocument):
        self.document = document
        super().__init__(f"Конфликт версии документа: текущая {document.version}")


def natural_key(name: str) -> tuple:
    """Ключ естественной сортировки: ``page2`` раньше ``page10``."""
    parts = _NUMBER_RE.split(str(name))
    key = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.casefold()))
    return tuple(key)


def _check_id(value: str) -> str:
    text = str(value or "")
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"Некорректный идентификатор: {value}")
    return text


def _new_id(taken: set[str]) -> str:
    for _ in range(16):
        value = uuid.uuid4().hex[:8]
        if value not in taken:
            return value
    raise RuntimeError("Не удалось выдать идентификатор")


def _path_key(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


_REPLACE_ATTEMPTS = 6
_REPLACE_DELAY = 0.05


def _clear_readonly(path: Path) -> None:
    """Снять «только чтение», иначе Windows не заменяет существующий файл."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & stat.S_IWRITE:
        return
    try:
        os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass


def _replace_file(temporary: Path, path: Path) -> None:
    """Заменить цель. Короткая блокировка на Windows даёт WinError 5."""
    delay = _REPLACE_DELAY
    last: PermissionError | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        _clear_readonly(path)
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            last = exc
            if attempt + 1 == _REPLACE_ATTEMPTS:
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
    assert last is not None
    raise last


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        _replace_file(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Ожидался объект JSON: {path}")
    return data


def _blank_page(version: int = 1) -> dict:
    return {
        "status": "idle",
        "progress": 0,
        "stage": "",
        "error": "",
        "warnings": [],
        "document": PageDocument(version=version).to_dict(),
    }


def _thumbnail(image: Image.Image, width: int = 160) -> Image.Image:
    rgb = image.convert("RGB")
    height = max(1, round(rgb.height * width / max(1, rgb.width)))
    return rgb.resize((width, height), Image.Resampling.LANCZOS)


class ProjectStore:
    """Каталог ``root / projects / <id>``."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def projects_dir(self) -> Path:
        return self.root / "projects"

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir() / _check_id(project_id)

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def page_dir(self, project_id: str, page_id: str) -> Path:
        return self.project_dir(project_id) / "pages" / _check_id(page_id)

    def create_project(self, name: str, source_lang: str, target_lang: str) -> dict:
        """Новый пустой проект."""
        taken = {item["id"] for item in self.list_projects()}
        project_id = _new_id(taken)
        title = str(name or "").strip() or "Проект"
        project = {
            "id": project_id,
            "name": title,
            "source_lang": str(source_lang or "en").strip() or "en",
            "target_lang": str(target_lang or "ru").strip() or "ru",
            "created": datetime.now(timezone.utc).isoformat(),
            "pages": [],
        }
        _write_json(self.project_file(project_id), project)
        return project

    def open_project(self, project_id: str) -> dict:
        path = self.project_file(project_id)
        if not path.is_file():
            raise FileNotFoundError(f"Проект не найден: {project_id}")
        project = _read_json(path)
        pages = []
        for record in project.get("pages") or []:
            if isinstance(record, dict):
                pages.append(_ensure_chapter(record))
        project["pages"] = pages
        return project

    def list_projects(self) -> list[dict]:
        folder = self.projects_dir()
        if not folder.is_dir():
            return []
        projects = []
        for entry in folder.iterdir():
            path = entry / "project.json"
            if entry.is_dir() and path.is_file():
                projects.append(_read_json(path))
        projects.sort(key=lambda item: (str(item.get("created") or ""), str(item.get("id") or "")))
        return projects

    def add_sources(
        self,
        project_id: str,
        paths: list[Path],
        chapter: str = "",
    ) -> list[dict]:
        """Добавить картинки верхнего уровня. Оригинал не копируется.

        Файлы с ``-mask`` в stem пропускаются. Повтор того же ``source_path``
        не добавляется. Новые страницы дописываются в естественном порядке имён.
        У всех одна глава ``chapter`` (по умолчанию пустая строка). Старые
        записи без ключа при записи получают ``chapter: ""``.
        """
        text = str(chapter or "")
        items = [(path, text) for path in _collect_sources(paths)]
        return self._add_items(project_id, items)

    def import_path(
        self,
        project_id: str,
        path: Path,
        *,
        recursive: bool = False,
        chapter_mode: str = "subdir",
    ) -> list[dict]:
        """Импорт папки или архива в открытый проект.

        Архив: zip, cbz, cbr, rar, cb7, 7z, cbt, tar. Картинки идут
        в естественном порядке, не глубже пяти папок. ``chapter_mode`` —
        ``subdir`` или ``flat`` (правило глав — в ``plan_chapters``).
        ``recursive`` относится к папке. Архив распаковывается в ``imports``
        проекта, zip-slip отсекает ``extract_archive``. Оригиналы папки
        не копируются. Архив без изображений поднимает ``NoImagesError``.
        """
        mode = str(chapter_mode or "flat")
        if mode not in ("subdir", "flat"):
            raise ValueError("Неизвестный режим глав")
        source = Path(path)
        if not source.exists():
            raise ValueError(f"Путь не найден: {source}")
        if is_archive(source):
            dest = self.project_dir(project_id) / "imports" / _safe_stem(source.stem)
            extracted = extract_archive(source, dest)
            planned = plan_chapters(
                extracted,
                mode,
                root=dest,
                archive_stem=source.stem,
            )
        elif source.is_dir():
            images = list_images(source, bool(recursive))
            planned = plan_chapters(images, mode, root=source)
        elif source.is_file() and is_image(source):
            planned = [(source, "")]
        else:
            raise ValueError(f"Не изображение и не архив: {source}")
        items = [
            (item, chapter)
            for item, chapter in planned
            if "-mask" not in Path(item).stem.lower()
        ]
        return self._add_items(project_id, items)

    def read_glossary(self, project_id: str) -> list[dict]:
        """Сохранённый список. Нет ключа — пустой список, без записи на диск."""
        project = self.open_project(project_id)
        raw = project.get("glossary")
        if not isinstance(raw, list):
            return []
        return normalize_glossary(raw)

    def write_glossary(self, project_id: str, entries: list) -> list[dict]:
        """Заменить глоссарий проекта нормализованным списком."""
        cleaned = normalize_glossary(entries if isinstance(entries, list) else [])
        project = self.open_project(project_id)
        project["glossary"] = cleaned
        _write_json(self.project_file(project_id), project)
        return cleaned

    def read_styles(self, project_id: str) -> list[dict]:
        """Библиотека стилей проекта. Нет ключа или пустой список — три стиля по умолчанию.

        На диск при чтении ничего не пишется: главы и глоссарий не меняются.
        """
        project = self.open_project(project_id)
        raw = project.get("styles")
        cleaned = _normalize_styles(raw)
        if not cleaned:
            return default_style_library()
        return cleaned

    def write_styles(self, project_id: str, styles: list) -> list[dict]:
        """Заменить библиотеку стилей. Остальные поля проекта остаются."""
        cleaned = _normalize_styles(styles)
        if not cleaned:
            cleaned = default_style_library()
        project = self.open_project(project_id)
        project["styles"] = cleaned
        _write_json(self.project_file(project_id), project)
        return cleaned

    def glossary_view(self, project_id: str) -> list[dict]:
        """Слить сохранённые записи с говорящими из документов страниц."""
        project = self.open_project(project_id)
        existing = project.get("glossary") if isinstance(project.get("glossary"), list) else []
        pages: list[dict] = []
        for record in project.get("pages") or []:
            page_id = str(record.get("id") or "")
            if not page_id:
                continue
            try:
                pages.append(self.read_document(project_id, page_id).to_dict())
            except (FileNotFoundError, ValueError, OSError):
                continue
        return glossary_from_pages(pages, existing)

    def _add_items(self, project_id: str, items: list[tuple[Path, str]]) -> list[dict]:
        """Дописать уже упорядоченные файлы. Порядок списка не меняется."""
        project = self.open_project(project_id)
        pages = [
            _ensure_chapter(item)
            for item in project.get("pages") or []
            if isinstance(item, dict)
        ]
        known = {
            _path_key(item.get("source_path") or "")
            for item in pages
            if item.get("source_path")
        }
        taken = {str(item.get("id") or "") for item in pages}
        added: list[dict] = []
        for source, chapter in items:
            path = Path(source)
            if not path.is_file():
                continue
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            if "-mask" in path.stem.lower():
                continue
            key = _path_key(path)
            if key in known:
                continue
            page_id = _new_id(taken)
            taken.add(page_id)
            record = _ensure_chapter(
                {
                    "id": page_id,
                    "source_path": str(path.resolve()),
                    "name": path.name,
                },
                chapter,
            )
            page_dir = self.page_dir(project_id, page_id)
            _write_json(page_dir / "page.json", _blank_page(version=1))
            self._write_thumb(path, page_dir / "thumb.jpg")
            pages.append(record)
            added.append(record)
            known.add(key)
        project["pages"] = pages
        _write_json(self.project_file(project_id), project)
        return added

    def remove_pages(self, project_id: str, page_ids: list[str]) -> None:
        """Удалить записи и каталоги страниц. Файл оригинала не трогать."""
        project = self.open_project(project_id)
        drop = {_check_id(page_id) for page_id in page_ids}
        kept = []
        for page in project.get("pages") or []:
            page_id = str(page.get("id") or "")
            if page_id in drop:
                shutil.rmtree(self.page_dir(project_id, page_id), ignore_errors=True)
                continue
            kept.append(page)
        project["pages"] = kept
        _write_json(self.project_file(project_id), project)

    def read_document(self, project_id: str, page_id: str) -> PageDocument:
        data = self._read_page(project_id, page_id)
        return PageDocument.from_dict(data.get("document") or {})

    def write_document(
        self,
        project_id: str,
        page_id: str,
        doc: PageDocument,
        base_version: int | None = None,
    ) -> PageDocument:
        """Записать документ и увеличить ``version`` на 1.

        Если ``base_version`` задан и не совпадает с текущим, бросает
        ``VersionConflict`` с документом, который сейчас на диске.
        """
        data = self._load_page(project_id, page_id)
        current = PageDocument.from_dict(data.get("document") or {"version": 0})
        if base_version is not None and int(base_version) != int(current.version):
            raise VersionConflict(current)
        doc.version = int(current.version) + 1
        data["document"] = doc.to_dict()
        data["warnings"] = list(doc.warnings)
        _write_json(self._page_file(project_id, page_id), data)
        return doc

    def read_auto(self, project_id: str, page_id: str) -> PageDocument:
        path = self.page_dir(project_id, page_id) / "auto.json"
        if not path.is_file():
            raise FileNotFoundError(f"Нет снимка auto.json: {page_id}")
        return PageDocument.from_dict(_read_json(path))

    def write_auto(self, project_id: str, page_id: str, doc: PageDocument) -> None:
        """Снимок пайплайна до ручных правок. Версию документа не увеличивает."""
        _write_json(self.page_dir(project_id, page_id) / "auto.json", doc.to_dict())

    def page_status(self, project_id: str, page_id: str) -> dict:
        data = self._read_page(project_id, page_id)
        return {
            "status": data.get("status") or "idle",
            "progress": int(data.get("progress") or 0),
            "stage": str(data.get("stage") or ""),
            "error": str(data.get("error") or ""),
            "warnings": list(data.get("warnings") or []),
        }

    def update_status(
        self,
        project_id: str,
        page_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        stage: str | None = None,
        error: str | None = None,
        warnings: list[str] | None = None,
    ) -> dict:
        data = self._load_page(project_id, page_id)
        if status is not None:
            if status not in _STATUSES:
                raise ValueError(f"Неизвестный статус: {status}")
            data["status"] = status
        if progress is not None:
            data["progress"] = max(0, min(100, int(progress)))
        if stage is not None:
            data["stage"] = str(stage)
        if error is not None:
            data["error"] = str(error)
        if warnings is not None:
            data["warnings"] = [str(item) for item in warnings]
        _write_json(self._page_file(project_id, page_id), data)
        return self.page_status(project_id, page_id)

    def image_path(self, project_id: str, page_id: str, kind: str) -> Path:
        name = _IMAGE_NAMES.get(kind)
        if name is None:
            raise ValueError(f"Неизвестный вид картинки: {kind}")
        return self.page_dir(project_id, page_id) / name

    def save_image(self, project_id: str, page_id: str, kind: str, image: Image.Image) -> Path:
        """Сохранить mask, clean, result или thumb. Оригинал страницы сюда не пишется."""
        path = self.image_path(project_id, page_id, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "thumb":
            _thumbnail(image).save(path, "JPEG", quality=85)
            return path
        image.save(path)
        return path

    def _page_file(self, project_id: str, page_id: str) -> Path:
        return self.page_dir(project_id, page_id) / "page.json"

    def _read_page(self, project_id: str, page_id: str) -> dict:
        path = self._page_file(project_id, page_id)
        if not path.is_file():
            raise FileNotFoundError(f"Страница не найдена: {page_id}")
        return _read_json(path)

    def _load_page(self, project_id: str, page_id: str) -> dict:
        path = self._page_file(project_id, page_id)
        if not path.is_file():
            return _blank_page(version=0)
        return _read_json(path)

    def _write_thumb(self, source: Path, dest: Path) -> None:
        with Image.open(source) as image:
            image.load()
            dest.parent.mkdir(parents=True, exist_ok=True)
            _thumbnail(image).save(dest, "JPEG", quality=85)


def default_style_library() -> list[dict]:
    """Диалог, крик (прописные и толще обводка) и звук."""
    plain = {
        "fill_rgb": [0, 0, 0],
        "stroke_rgb": None,
        "font_size": 16,
        "alignment": "center",
        "uppercase": False,
        "line_height": 18,
        "font_size_override": 0,
        "font_id": "",
        "stroke_mode": "auto",
        "stroke_width": 0,
        "letter_spacing": 0,
        "line_spacing": 0,
        "rotation": 0,
        "skew_x": 0,
        "warp": {"kind": "none", "bend": 0, "quad": None, "mesh": None},
    }
    shout = {
        **plain,
        "uppercase": True,
        "font_size": 28,
        "line_height": 30,
        "stroke_rgb": [0, 0, 0],
        "stroke_mode": "custom",
        "stroke_width": 6,
    }
    sfx = {
        **plain,
        "uppercase": True,
        "font_size": 32,
        "line_height": 34,
        "fill_rgb": [255, 255, 255],
        "stroke_rgb": [17, 17, 17],
        "stroke_mode": "custom",
        "stroke_width": 4,
        "warp": {"kind": "arc", "bend": 0.35, "quad": None, "mesh": None},
    }
    return [
        {"name": "Диалог", "style": plain},
        {"name": "Крик", "style": shout},
        {"name": "SFX", "style": sfx},
    ]


def _normalize_styles(raw) -> list[dict]:
    """Список ``{name, style}``. Пустое имя и не-словари отбрасываются."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        style = item.get("style")
        if not name or not isinstance(style, dict):
            continue
        cleaned.append({"name": name, "style": dict(style)})
    return cleaned


def _ensure_chapter(record: dict, chapter: str | None = None) -> dict:
    """Копия записи страницы с полем ``chapter``. Нет ключа — пустая строка."""
    item = dict(record)
    if chapter is None:
        item["chapter"] = str(item.get("chapter") or "")
    else:
        item["chapter"] = str(chapter or "")
    return item


def _safe_stem(stem: str) -> str:
    """Имя каталога распаковки без разделителей пути."""
    cleaned = re.sub(r"[^\w.\-]+", "_", str(stem), flags=re.UNICODE).strip("._")
    return cleaned or "archive"


def _collect_sources(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(item for item in path.iterdir() if item.is_file())
        elif path.is_file():
            files.append(path)
    selected = []
    for path in files:
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        if "-mask" in path.stem.lower():
            continue
        selected.append(path)
    selected.sort(key=lambda item: natural_key(item.name))
    return selected
