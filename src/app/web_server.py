"""Серверный редактор: явная сетевая политика и управляемые файлы браузера."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import threading
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

MAX_UPLOAD = 256 * 1024 * 1024
_ID = re.compile(r"^[a-f0-9]{32}$")
_JOB_ID = re.compile(r"^[a-f0-9]{8,32}$")
_PATH_SETTINGS = {"models_dir", "components_dir", "components_previous_dir", "glossary_path"}
_BLOCKED = {"/api/drop", "/api/import", "/api/jobs/export", "/api/project/package/load",
            "/api/project/package/save", "/api/runtime/download", "/api/runtime/remove",
            "/api/models/download", "/api/preparation/start", "/api/preparation/pause",
            "/api/preparation/verify",
            "/api/preparation/resume", "/api/preparation/location", "/api/preparation/cache/clear"}


def validate_origins(origins) -> tuple[str, ...]:
    """Только точные HTTP(S) origins, без wildcard, пути и учётных данных."""
    result = []
    for value in origins:
        text = str(value).strip().rstrip("/")
        parsed = urlsplit(text)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in text):
            raise ValueError("ILT_WEB_ORIGINS должен содержать точные HTTP(S) адреса без пути")
        parsed.port
        result.append(text.lower())
    if not result:
        raise ValueError("Нужен хотя бы один публичный адрес сервера")
    return tuple(result)


def request_allowed(handler, origins: tuple[str, ...]) -> bool:
    """Не доверять присланным forwarded-заголовкам при проверке Host/Origin."""
    hosts = {urlsplit(origin).netloc for origin in origins}
    host = (handler.headers.get("Host") or "").lower()
    origin = handler.headers.get("Origin")
    return host in hosts and (origin is None or origin.lower() in origins)


def guard_api(method: str, path: str, body: dict) -> None:
    """Удалённый клиент не выбирает пути на сервере и не меняет образ."""
    from src.app.server import _HttpError

    if path.startswith("/api/dialog/") or path in _BLOCKED:
        raise _HttpError(403, "В браузере используйте загрузку и скачивание файлов")
    if path == "/api/settings" and method == "PUT":
        if any(body.get(key) for key in _PATH_SETTINGS) or body.get("remote_enabled"):
            raise _HttpError(403, "Каталоги и слушатели задаются при запуске сервера")


def _attachment(path: Path, filename: str):
    from src.app.server import _Result

    return _Result(file=path, content_type="application/zip",
                   headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _upload(handler, state, query: dict):
    from PIL import Image, UnidentifiedImageError
    from src.app.ingest import IMAGE_SUFFIXES
    from src.app.server import _HttpError, _add_paths

    name = str(query.get("name", [""])[0])
    chapter = str(query.get("chapter", [""])[0])
    if len(chapter) > 200 or any(char in chapter for char in '\\:\x00\r\n') or ".." in chapter.split("/"):
        raise ValueError("Недопустимое имя главы")
    if (not name or len(name) > 200 or name in {".", ".."}
            or any(char in name for char in '/\\:\x00\r\n') or name.startswith(".")):
        raise ValueError("Недопустимое имя файла")
    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_SUFFIXES | {".zip", ".cbz"}:
        raise ValueError("Загрузите изображение, ZIP, CBZ или проект .ilt.zip")
    raw_length = handler.headers.get("Content-Length", "")
    if not raw_length.isdecimal() or handler.headers.get("Transfer-Encoding"):
        raise _HttpError(411, "Нужен Content-Length")
    size = int(raw_length)
    if not 0 < size <= MAX_UPLOAD:
        raise _HttpError(413, "Размер файла должен быть от 1 байта до 256 МиБ")
    folder = state.store.root / "imports" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    path = folder / name
    previous_timeout = handler.connection.gettimeout()
    try:
        handler.connection.settimeout(60)
        handler._ilt_body_read = True
        with path.open("xb") as target:
            remaining = size
            while remaining:
                chunk = handler.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Загрузка оборвалась")
                target.write(chunk)
                remaining -= len(chunk)
        if suffix in IMAGE_SUFFIXES:
            try:
                with Image.open(path) as image:
                    image.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValueError("Повреждённое изображение") from exc
        else:
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    if len(entries) > 10000 or sum(item.file_size for item in entries) > 2 * 1024**3:
                        raise ValueError("Архив слишком большой после распаковки")
            except zipfile.BadZipFile as exc:
                raise ValueError("Повреждённый ZIP-архив") from exc
        # Оригинал остаётся здесь: ProjectStore сохраняет source_path без копирования.
        return _add_paths(state, [path], strict=True, chapter=chapter)
    except Exception:
        shutil.rmtree(folder)
        raise
    finally:
        handler.connection.settimeout(previous_timeout)


def note_export(state, job_id: str) -> None:
    """Сохранить терминальный статус скачивания также после перезапуска."""
    from src.app.downloads import atomic_json

    if not _JOB_ID.fullmatch(job_id):
        return
    path = state.store.root / "exports" / f"{job_id}.json"
    if not path.is_file():
        return
    status = state.queue.job_status(job_id)
    if status not in {"done", "error", "cancelled"}:
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    atomic_json(path, data)


def _export(state, body: dict) -> dict:
    from src.app.downloads import atomic_json
    from src.app.server import _export as submit_export

    if body.get("dest"):
        raise ValueError("Назначение экспорта выбирает сервер")
    folder_id = uuid.uuid4().hex
    project_id = state.project_id
    folder = state.store.root / "exports" / folder_id
    folder.mkdir(parents=True)
    previous = state.export_dir
    try:
        state.export_dir = folder
        result = submit_export(state, {**body, "archive": "zip"})
    finally:
        state.export_dir = previous
    job_id = result["job_id"]
    atomic_json(folder.parent / f"{job_id}.json", {"project_id": project_id,
        "folder": folder_id, "status": "queued"})
    note_export(state, job_id)
    return {**result, "download_url": f"/api/browser/export/{job_id}"}


def _download_export(state, job_id: str):
    from src.app.server import _HttpError

    if not _JOB_ID.fullmatch(job_id):
        raise FileNotFoundError(job_id)
    root = state.store.root / "exports"
    metadata = json.loads((root / f"{job_id}.json").read_text(encoding="utf-8"))
    if metadata["project_id"] != state.project_id or not _ID.fullmatch(metadata["folder"]):
        raise FileNotFoundError(job_id)
    status = state.queue.job_status(job_id) or metadata["status"]
    if status != "done":
        raise _HttpError(409, "Экспорт ещё не готов или завершился с ошибкой")
    return _attachment(root / metadata["folder"] / "export.zip", "translated-pages.zip")


def browser_route(handler, state, method: str, path: str, query: dict) -> None:
    from src.app.server import _HttpError, _Result, _need_method, _package_save, _read_json, _send_result

    body = _read_json(handler) if method in ("POST", "PUT") and path != "/api/browser/upload" else {}
    # Один shared project: смена проекта и файловые операции не должны пересекаться.
    with state._browser_files_lock:
        from src.app.server import _cookie_ok, _cookie_value
        from src.app.web_access import AccessDenied, AccessLimited

        if not _cookie_ok(handler, state):
            raise _HttpError(401, "Войдите в редактор заново")
        if path == "/api/browser/logout":
            _need_method(method, "POST")
            state.web_access.logout(_cookie_value(handler.headers.get("Cookie") or "", "ilt_browser_session"))
            result = _Result({"ok": True})
        elif path == "/api/browser/access":
            if method == "GET":
                result = _Result(state.web_access.status())
            else:
                _need_method(method, "PUT")
                try:
                    status, token = state.web_access.update(body,
                        _cookie_value(handler.headers.get("Cookie") or "", "ilt_browser_session"))
                except (AccessDenied, AccessLimited) as exc:
                    raise _HttpError(429 if isinstance(exc, AccessLimited) else 401, str(exc)) from exc
                result = _Result(status, cookie=token)
        elif path == "/api/browser/upload":
            _need_method(method, "POST")
            result = _Result(_upload(handler, state, query))
        elif path == "/api/browser/export":
            _need_method(method, "POST")
            result = _Result(_export(state, body))
        elif path.startswith("/api/browser/export/"):
            _need_method(method, "GET")
            result = _download_export(state, path.rsplit("/", 1)[-1])
        elif path == "/api/browser/project":
            _need_method(method, "POST")
            package_id = uuid.uuid4().hex
            folder = state.store.root / "packages"
            folder.mkdir(exist_ok=True)
            result_body = _package_save(state, {"path": str(folder / f"{package_id}.ilt.zip"),
                                                 "editor": body.get("editor")})
            from src.app.downloads import atomic_json

            atomic_json(folder / f"{package_id}.json", {"project_id": state.project_id})
            result_body["download_url"] = f"/api/browser/project/{package_id}"
            result = _Result(result_body)
        elif path.startswith("/api/browser/project/"):
            _need_method(method, "GET")
            package_id = path.rsplit("/", 1)[-1]
            if not _ID.fullmatch(package_id):
                raise FileNotFoundError(package_id)
            metadata = json.loads((state.store.root / "packages" / f"{package_id}.json").read_text(encoding="utf-8"))
            if metadata["project_id"] != state.project_id:
                raise FileNotFoundError(package_id)
            result = _attachment(state.store.root / "packages" / f"{package_id}.ilt.zip", "project.ilt.zip")
        else:
            raise _HttpError(404, "Не найдено")
    _send_result(handler, result)


def run() -> int:
    """Один редактор на экземпляр; SIGTERM корректно завершает worker и очередь."""
    from src.app.desktop import DesktopApp
    from src.app.dialogs import DialogBridge
    from src.app.jobs import JobQueue
    from src.app.paths import ensure_data_root, settings_path
    from src.app.server import AppState, serve, _open_recent
    from src.app.settings import AppSettings
    from src.app.store import ProjectStore
    from src.app.worker import ProcessWorker

    root = ensure_data_root()
    from src.app.distribution import seed_data

    seed_data(root)
    settings, warnings = AppSettings.load(settings_path())
    if not settings_path().exists():
        settings = AppSettings(ocr_backend="rapid", translator_backend="argos", device="cpu", first_run_complete=True)
    # Пути компонентов фиксируются развёртыванием, не старой конфигурацией desktop.
    settings.models_dir = settings.components_dir = settings.components_previous_dir = settings.glossary_path = ""
    settings.remote_enabled = False
    port = int(os.environ.get("ILT_WEB_PORT", "8080"))
    origins = validate_origins(os.environ.get("ILT_WEB_ORIGINS",
        f"http://localhost:{port},http://127.0.0.1:{port}").split(","))
    state = AppState(settings, settings_path(), ProjectStore(root), JobQueue(ProcessWorker()),
                     dialogs=DialogBridge(), settings_warnings=warnings)
    httpd, _ = serve(state, host=os.environ.get("ILT_WEB_BIND", "0.0.0.0"), port=port, origins=origins)
    app = DesktopApp(state, httpd, endpoint=None)
    for project_id in settings.recent_projects:
        try:
            _open_recent(state, {"id": project_id})
            break
        except (ValueError, FileNotFoundError):
            continue
    stopped = threading.Event()
    previous = {}
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name)
        previous[signum] = signal.signal(signum, lambda *_: stopped.set())
    try:
        app._start_http_thread()
        protection = "вход по логину и паролю" if state.web_access.status()["enabled"] else "без обязательного входа"
        print(f"Редактор: {origins[0]}; {protection}. Настройки → Доступ", flush=True)
        stopped.wait()
    finally:
        app.shutdown()
        for signum, old in previous.items():
            signal.signal(signum, old)
    return 0
