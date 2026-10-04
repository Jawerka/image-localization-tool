"""Локальный HTTP API настольного приложения.

Слушает только ``127.0.0.1``. Страница открывается с ``/?k=<token>``:
в ответ ставится cookie ``ilt_session``, без редиректа. Дальше ``/api/*``
принимает только эту cookie. ``POST /api/session`` — тот же обмен по токену
из тела, без cookie.

Пути к файлам из JSON не читаются, кроме ``POST /api/drop`` и ``POST /api/import``.
Папку экспорта задаёт диалог, а не поле ``dest``.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

from src.app import __version__, model_manager
from src.app.dialogs import DialogBridge
from src.app.document import PageDocument, diff_plan
from src.app.events import LLM_STATUS, WorkerEvent
from src.app.ingest import NoImagesError, archive_images, is_archive
from src.app.jobs import JobQueue
from src.app.settings import AppSettings, get_api_key
from src.app.store import ProjectStore, VersionConflict
from src.app.worker import demote_restored_running, queue_has_unfinished
from src.utils.paths import install_root

logger = logging.getLogger("ilt.app.server")

_MAX_BODY = 8 * 1024 * 1024
_COOKIE = "ilt_session"
_SSE_KEEPALIVE_SEC = 15
_IMAGE_KINDS = frozenset({"original", "result", "clean", "mask", "thumb"})
_REGION_ACTIONS = frozenset({"recognize", "retranslate", "shorten"})
_PAGE_ID = re.compile(r"^/api/pages/([^/]+)$")
_PAGE_DOCUMENT = re.compile(r"^/api/pages/([^/]+)/document$")
_PAGE_RESET = re.compile(r"^/api/pages/([^/]+)/reset$")
_PAGE_ACTION = re.compile(r"^/api/pages/([^/]+)/action$")
_PAGE_IMAGE = re.compile(r"^/api/pages/([^/]+)/image/([^/]+)$")
_PAGE_PREVIEW = re.compile(r"^/api/pages/([^/]+)/preview-region$")
_PAGE_SFX = re.compile(r"^/api/pages/([^/]+)/regions/([^/]+)/sfx-style$")
_FONT_PREVIEW = re.compile(r"^/api/fonts/([^/]+)/preview$")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".ico": "image/x-icon",
}


class _HttpError(Exception):
    """Ответ с кодом и JSON ``{"error": ...}``."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.payload = {"error": message, **extra}


class _Result:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        status: int = 200,
        body: bytes | None = None,
        content_type: str | None = None,
        cookie: str | None = None,
        headers: dict | None = None,
    ):
        self.payload = payload
        self.status = status
        self.body = body
        self.content_type = content_type
        self.cookie = cookie
        self.headers = dict(headers or {})


def _same_token(got: str, expected: str) -> bool:
    if not got or not expected:
        return False
    left = got.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def _cookie_header(token: str) -> str:
    return f"{_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"


def _cookie_value(header: str) -> str:
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == _COOKIE:
            return value
    return ""


def _same_path(left: Path, right: Path) -> bool:
    try:
        a = os.path.normcase(str(Path(left).resolve()))
        b = os.path.normcase(str(Path(right).resolve()))
    except (OSError, ValueError):
        return False
    return a == b


def _default_web_root() -> Path:
    """Каталог ``web`` рядом с программой.

    В сборке это папка exe (spec кладёт ``web`` туда, не в ``_internal``).
    Из исходников ``install_root()`` — корень репозитория, тот же путь, что и раньше.
    """
    bundled = install_root() / "web"
    if (bundled / "index.html").is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / "web"


class AppState:
    """Состояние одного локального сервера и текущего проекта."""

    def __init__(
        self,
        settings: AppSettings,
        settings_path: Path,
        store: ProjectStore,
        queue: JobQueue,
        dialogs: DialogBridge | None = None,
        web_root: Path | None = None,
        settings_warnings: list[str] | None = None,
        project_id: str | None = None,
        token: str | None = None,
    ):
        self.settings = settings
        self.settings_path = Path(settings_path)
        self.settings_warnings = list(settings_warnings or [])
        self.store = store
        self.queue = queue
        self.dialogs = dialogs if dialogs is not None else DialogBridge()
        self.project_id = project_id
        self.web_root = Path(web_root) if web_root is not None else _default_web_root()
        self.token = token or secrets.token_urlsafe(32)
        self.subscribers: list[queue.Queue] = []
        self.export_dir: Path | None = None
        self.reveal_path: Path | None = None
        self.llm_status = {"ok": None, "models": []}
        self.port = 0
        self._lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._drain_lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self._pump: threading.Thread | None = None
        self.queue_pending = False
        self._queue_restored = False

    def queue_path(self) -> Path:
        """JSON очереди рядом с проектами."""
        return self.store.root / "queue.json"

    def start(self) -> None:
        """Фоновая раздача событий очереди подписчикам SSE."""
        if self._pump is not None and self._pump.is_alive():
            return
        if not self._queue_restored:
            self._queue_restored = True
            self._restore_saved_queue()
        self._stop.clear()
        self._pump = threading.Thread(target=self._pump_loop, name="ilt-events", daemon=True)
        self._pump.start()
        self._start_llm_probe()

    def _start_llm_probe(self) -> None:
        """Проверить LLM в фоне. Пустой адрес — сразу «нет», без баннера до ответа."""
        url = str(self.settings.llm_base_url or "").strip()
        if not url:
            self.llm_status = {"ok": False, "models": [], "reason": "empty"}
            return
        self.llm_status = {"ok": None, "models": []}
        threading.Thread(target=self._probe_llm, name="ilt-llm", daemon=True).start()

    def _probe_llm(self) -> None:
        from src.app.settings import get_api_key

        url = str(self.settings.llm_base_url or "").strip()
        result = model_manager.check_llm(url, get_api_key())
        if not result.get("ok") and url:
            if self._stop.wait(2):
                return
            result = model_manager.check_llm(url, get_api_key())
        models = [str(item) for item in result.get("models") or []]
        self.llm_status = {
            "ok": bool(result.get("ok")),
            "models": models,
            "reason": str(result.get("reason") or ""),
        }
        self.fanout(WorkerEvent(LLM_STATUS, {
            "ok": bool(result.get("ok")),
            "models": models,
            "reason": str(result.get("reason") or ""),
        }))

    def close(self) -> None:
        """Остановить раздачу и разбудить висящие SSE."""
        with self._sub_lock:
            if self._closed:
                return
            self._closed = True
            boxes = list(self.subscribers)
        self._stop.set()
        for box in boxes:
            box.put(None)
        _save_queue(self)
        pump = self._pump
        if pump is not None and pump.is_alive() and threading.current_thread() is not pump:
            pump.join(timeout=1)

    def subscribe(self) -> queue.Queue:
        box: queue.Queue = queue.Queue()
        with self._sub_lock:
            self.subscribers.append(box)
        return box

    def unsubscribe(self, box: queue.Queue) -> None:
        with self._sub_lock:
            try:
                self.subscribers.remove(box)
            except ValueError:
                return

    def fanout(self, event: WorkerEvent) -> None:
        payload = event.to_dict()
        with self._sub_lock:
            boxes = list(self.subscribers)
        for box in boxes:
            box.put(payload)

    def broadcast_pending(self) -> None:
        """Забрать события воркера и отдать каждому подписчику."""
        with self._drain_lock:
            events = list(self.queue.drain_events())
        for event in events:
            self.fanout(event)

    def _pump_loop(self) -> None:
        while not self._stop.is_set():
            self.broadcast_pending()
            self._stop.wait(0.05)
        self.broadcast_pending()

    def _restore_saved_queue(self) -> None:
        """Поднять очередь с диска. Незаконченное не стартует само: пауза."""
        path = self.queue_path()
        pending = queue_has_unfinished(path)
        try:
            self.queue.load(path)
        except (OSError, json.JSONDecodeError, UnicodeError, ValueError):
            logger.exception("Не удалось прочитать очередь")
            self.queue_pending = False
            return
        self.queue_pending = pending
        if pending and not self.queue.paused:
            self.queue.pause()
        snap = self.queue.snapshot()
        demote_restored_running(
            self.store,
            list(snap.get("batch") or []) + list(snap.get("edits") or []),
        )


class _AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def shutdown(self) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.close()
        super().shutdown()

    def server_close(self) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.close()
        super().server_close()


def serve(
    state: AppState,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, int]:
    """Поднять сервер на ``127.0.0.1`` и случайном порте. Цикл — у вызывающего."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Сервер слушает только 127.0.0.1")
    server = _AppServer(("127.0.0.1", int(port)), _make_handler(state))
    server.app_state = state
    bound = int(server.server_address[1])
    state.port = bound
    state.start()
    return server, bound


def _make_handler(state: AppState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            logger.debug("%s %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            self.close_connection = True
            try:
                self._route()
            except _HttpError as exc:
                _send_json(self, exc.payload, exc.status)
            except VersionConflict as exc:
                _send_json(
                    self,
                    {"error": "Конфликт версии", "document": exc.document.to_dict()},
                    409,
                )
            except FileNotFoundError:
                _send_json(self, {"error": "Не найдено"}, 404)
            except json.JSONDecodeError:
                _send_json(self, {"error": "Некорректный JSON"}, 400)
            except ValueError as exc:
                _send_json(self, {"error": str(exc) or "Некорректный запрос"}, 400)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except Exception:
                logger.exception("Ошибка HTTP")
                try:
                    _send_json(self, {"error": "Внутренняя ошибка"}, 500)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                    return
            finally:
                if self.command != "GET" or urlparse(self.path).path != "/api/events":
                    state.broadcast_pending()

    def _route_impl(handler: Handler) -> None:
        port = int(handler.server.server_address[1])
        if not _host_allowed(handler.headers.get("Host"), port):
            _send_json(handler, {"error": "Запрос отклонён"}, 403)
            return
        if not _origin_allowed(handler.headers.get("Origin"), port):
            _send_json(handler, {"error": "Запрос отклонён"}, 403)
            return

        parsed = urlparse(handler.path)
        path = unquote(parsed.path or "/")
        query = parse_qs(parsed.query, keep_blank_values=True)
        method = handler.command

        if method == "GET" and path == "/api/events":
            if not _cookie_ok(handler, state):
                _send_json(handler, {"error": "Не авторизован"}, 401)
                return
            _stream_events(handler, state)
            return

        if method == "POST" and path == "/api/session":
            body = _read_json(handler)
            _handle_session(handler, state, body)
            return

        if path.startswith("/api/"):
            if not _cookie_ok(handler, state):
                _send_json(handler, {"error": "Не авторизован"}, 401)
                return
            if method == "PUT" and path == "/api/project/glossary":
                body = _glossary_put_body(handler)
            elif method in ("POST", "PUT"):
                body = _read_json(handler)
            else:
                body = {}
            result = _api(state, method, path, body, query)
            _send_result(handler, result)
            return

        if method != "GET":
            _send_json(handler, {"error": "Метод не поддерживается"}, 405)
            return
        _send_result(handler, _static(state, path, query))

    Handler._route = _route_impl  # type: ignore[attr-defined]
    return Handler


def _host_allowed(value: str | None, port: int) -> bool:
    if not value:
        return False
    text = value.strip().lower()
    return text in {f"127.0.0.1:{port}", f"localhost:{port}"}


def _origin_allowed(value: str | None, port: int) -> bool:
    if value is None:
        return True
    text = value.strip()
    if text == "":
        return True
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    return text in allowed or text.lower() in allowed


def _cookie_ok(handler: BaseHTTPRequestHandler, state: AppState) -> bool:
    return _same_token(_cookie_value(handler.headers.get("Cookie") or ""), state.token)


def _read_body(handler: BaseHTTPRequestHandler) -> object:
    length_raw = handler.headers.get("Content-Length")
    if length_raw is None or length_raw == "":
        return {}
    try:
        length = int(length_raw)
    except ValueError as exc:
        raise ValueError("Некорректный Content-Length") from exc
    if length < 0 or length > _MAX_BODY:
        raise ValueError("Слишком большой запрос")
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    data = _read_body(handler)
    if data == {}:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект")
    return data


def _glossary_put_body(handler: BaseHTTPRequestHandler) -> dict:
    """Тело PUT: JSON-список или объект с полем ``glossary``."""
    data = _read_body(handler)
    if isinstance(data, list):
        return {"glossary": data}
    if isinstance(data, dict):
        raw = data.get("glossary", data.get("entries"))
        if isinstance(raw, list):
            return {"glossary": raw}
    raise ValueError("Нужен список глоссария")


def _handle_session(handler: BaseHTTPRequestHandler, state: AppState, body: dict) -> None:
    token = body.get("token")
    if not isinstance(token, str) or not _same_token(token, state.token):
        _send_json(handler, {"error": "Не авторизован"}, 401)
        return
    _send_json(handler, {"ok": True}, cookie=state.token)


def _api(state: AppState, method: str, path: str, body: dict, query: dict | None = None) -> _Result:
    if path == "/api/bootstrap":
        _need_method(method, "GET")
        return _Result(_bootstrap(state))
    if path == "/api/pages":
        raise _HttpError(404, "Не найдено")

    matched = _PAGE_DOCUMENT.fullmatch(path)
    if matched:
        _need_method(method, "PUT")
        return _Result(_put_document(state, _page_id(matched.group(1)), body))
    matched = _PAGE_RESET.fullmatch(path)
    if matched:
        _need_method(method, "POST")
        return _Result(_reset_page(state, _page_id(matched.group(1))))
    matched = _PAGE_ACTION.fullmatch(path)
    if matched:
        _need_method(method, "POST")
        return _Result(_page_action(state, _page_id(matched.group(1)), body))
    matched = _PAGE_IMAGE.fullmatch(path)
    if matched:
        _need_method(method, "GET")
        return _image(state, _page_id(matched.group(1)), matched.group(2))
    matched = _PAGE_ID.fullmatch(path)
    if matched:
        _need_method(method, "GET")
        return _Result(_page_detail(state, _page_id(matched.group(1))))

    if path == "/api/jobs":
        _need_method(method, "GET")
        return _Result(_jobs_view(state))
    if path == "/api/jobs/translate":
        _need_method(method, "POST")
        return _Result(_translate(state, body))
    if path == "/api/jobs/cancel":
        _need_method(method, "POST")
        return _Result(_cancel(state))
    if path == "/api/jobs/pause":
        _need_method(method, "POST")
        return _Result(_pause_jobs(state))
    if path == "/api/jobs/resume":
        _need_method(method, "POST")
        return _Result(_resume_jobs(state))
    if path == "/api/jobs/retry-errors":
        _need_method(method, "POST")
        return _Result(_retry_errors(state))
    if path == "/api/jobs/export":
        _need_method(method, "POST")
        return _Result(_export(state, body))
    if path == "/api/import":
        _need_method(method, "POST")
        return _Result(_import_sources(state, body))
    if path == "/api/dialog/directory":
        _need_method(method, "POST")
        return _Result(_dialog_directory(state))
    if path == "/api/dialog/files":
        _need_method(method, "POST")
        return _Result(_dialog_files(state))
    if path == "/api/dialog/folder":
        _need_method(method, "POST")
        return _Result(_dialog_folder(state, body))
    if path == "/api/dialog/log":
        _need_method(method, "POST")
        state.dialogs.open_log()
        return _Result({"ok": True})
    if path == "/api/dialog/reveal":
        _need_method(method, "POST")
        return _Result(_reveal(state))
    if path == "/api/settings":
        _need_method(method, "PUT")
        return _Result({"settings": _update_settings(state, body)})
    if path == "/api/settings/secret":
        _need_method(method, "POST")
        return _Result(_set_secret(state, body))
    if path == "/api/llm/check":
        _need_method(method, "POST")
        return _Result(_check_llm(state))
    if path == "/api/models":
        _need_method(method, "GET")
        return _Result(model_manager.status(state.settings.models_dir))
    if path == "/api/models/download":
        _need_method(method, "POST")
        _download_model(state, body)
        return _Result({"ok": True}, status=202)
    if path == "/api/drop":
        _need_method(method, "POST")
        return _Result(_drop(state, body))
    if path == "/api/project/glossary":
        if method == "GET":
            return _Result(_get_glossary(state))
        if method == "PUT":
            return _Result(_put_glossary(state, body))
        raise _HttpError(405, "Метод не поддерживается")
    if path == "/api/project/styles":
        if method == "GET":
            return _Result(_get_styles(state))
        if method == "PUT":
            return _Result(_put_styles(state, body))
        raise _HttpError(405, "Метод не поддерживается")
    if path == "/api/fonts":
        _need_method(method, "GET")
        return _Result(_font_list())
    matched = _FONT_PREVIEW.fullmatch(path)
    if matched:
        _need_method(method, "GET")
        return _font_preview(unquote(matched.group(1)), query or {})
    matched = _PAGE_PREVIEW.fullmatch(path)
    if matched:
        _need_method(method, "POST")
        return _preview_region(state, _page_id(matched.group(1)), body)
    matched = _PAGE_SFX.fullmatch(path)
    if matched:
        _need_method(method, "POST")
        return _Result(_apply_sfx_style(state, _page_id(matched.group(1)), unquote(matched.group(2))))
    if path == "/api/remote/status":
        _need_method(method, "GET")
        return _Result(_remote_status(state))
    if path == "/api/remote/pair-code":
        _need_method(method, "POST")
        return _Result(_remote_pair(state))
    if path == "/api/remote/revoke":
        _need_method(method, "POST")
        return _Result(_remote_revoke(state, body))
    if path == "/api/project/remove-pages":
        _need_method(method, "POST")
        return _Result(_remove_pages(state, body))
    if path == "/api/project/open-recent":
        _need_method(method, "POST")
        return _Result(_open_recent(state, body))
    raise _HttpError(404, "Не найдено")


def _need_method(method: str, expected: str) -> None:
    if method != expected:
        raise _HttpError(405, "Метод не поддерживается")


def _page_id(raw: str) -> str:
    return unquote(raw)


def _bootstrap(state: AppState) -> dict:
    project, pages = _project_and_pages(state)
    warning = ""
    if state.settings_warnings:
        warning = str(state.settings_warnings[0] or "")
    llm = state.llm_status
    if llm.get("ok") is None:
        llm_view = {"ok": None, "models": []}
    elif not llm.get("ok"):
        llm_view = {"ok": False, "models": []}
    else:
        llm_view = {"ok": True, "models": [str(item) for item in llm.get("models") or []]}
    info = model_manager.status(state.settings.models_dir)
    ready = all(bool((info.get(name) or {}).get("present")) for name in ("detector", "lama", "font"))
    return {
        "version": __version__,
        "settings": state.settings.to_dict(),
        "settings_warning": warning,
        "project": project,
        "pages": pages,
        "llm": llm_view,
        "device": state.settings.device,
        "models_ready": ready,
        "busy": any(page["status"] in ("queued", "running") for page in pages),
        "recent": _recent_view(state),
        "has_api_key": bool(get_api_key()),
        "paths": {
            "settings": str(state.settings_path),
            "data": str(state.store.root),
        },
    }


def _project_and_pages(state: AppState) -> tuple[dict | None, list[dict]]:
    if not state.project_id:
        return None, []
    try:
        project = state.store.open_project(state.project_id)
    except FileNotFoundError:
        return None, []
    pages = []
    for record in project.get("pages") or []:
        pages.append(_page_row(state, record))
    return project, pages


def _collection(state: AppState) -> dict:
    project, pages = _project_and_pages(state)
    return {"project": project, "pages": pages}


def _page_row(state: AppState, record: dict) -> dict:
    page_id = str(record.get("id") or "")
    status = state.store.page_status(state.project_id or "", page_id)
    return {
        "id": page_id,
        "name": str(record.get("name") or ""),
        "source_path": str(record.get("source_path") or ""),
        "chapter": str(record.get("chapter") or ""),
        "status": status["status"],
        "progress": status["progress"],
        "stage": status["stage"],
        "error": status["error"],
        "warnings": status["warnings"],
    }


def _require_page(state: AppState, page_id: str) -> dict:
    if not state.project_id:
        raise FileNotFoundError(page_id)
    project = state.store.open_project(state.project_id)
    for record in project.get("pages") or []:
        if str(record.get("id") or "") == page_id:
            return record
    raise FileNotFoundError(page_id)


def _page_detail(state: AppState, page_id: str) -> dict:
    record = _require_page(state, page_id)
    row = _page_row(state, record)
    row["document"] = state.store.read_document(state.project_id or "", page_id).to_dict()
    return row


def _put_document(state: AppState, page_id: str, body: dict) -> dict:
    if "base_version" not in body:
        raise ValueError("Нужна base_version")
    base_version = body.get("base_version")
    if isinstance(base_version, bool) or not isinstance(base_version, int):
        raise ValueError("Некорректная base_version")
    raw = body.get("document")
    if not isinstance(raw, dict):
        raise ValueError("Нужен документ")
    _require_page(state, page_id)
    project_id = state.project_id or ""
    previous = state.store.read_document(project_id, page_id)
    updated = PageDocument.from_dict(raw)
    plan = diff_plan(previous, updated)
    try:
        saved = state.store.write_document(
            project_id,
            page_id,
            updated,
            base_version=base_version,
        )
    except VersionConflict as exc:
        raise _HttpError(409, "Конфликт версии", document=exc.document.to_dict()) from exc
    if plan in ("typeset", "clean"):
        state.store.update_status(project_id, page_id, status="edited")
        _submit(
            state,
            "apply_document",
            page_id,
            {
                "plan": plan,
                "document": saved.to_dict(),
                "base_version": int(saved.version),
            },
        )
    return {"document": saved.to_dict(), "plan": plan}


def _reset_page(state: AppState, page_id: str) -> dict:
    _require_page(state, page_id)
    project_id = state.project_id or ""
    snapshot = state.store.read_auto(project_id, page_id)
    saved = state.store.write_document(project_id, page_id, snapshot)
    state.store.update_status(project_id, page_id, status="edited")
    _submit(
        state,
        "apply_document",
        page_id,
        {
            "plan": "clean",
            "document": saved.to_dict(),
            "base_version": int(saved.version),
        },
    )
    return {"document": saved.to_dict(), "plan": "clean"}


def _page_action(state: AppState, page_id: str, body: dict) -> dict:
    action = str(body.get("action") or "")
    if action not in _REGION_ACTIONS:
        raise ValueError("Неизвестное действие")
    region_id = _region_id(body.get("region_id"))
    _require_page(state, page_id)
    job = _submit(state, action, page_id, {"region_id": region_id})
    return {"job_id": job.id}


def _region_id(value) -> int:
    if isinstance(value, bool):
        raise ValueError("Нужен region_id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError("Нужен region_id")


def _translate(state: AppState, body: dict) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    scope = str(body.get("scope") or "")
    skip = bool(body.get("skip_ready"))
    project = state.store.open_project(state.project_id)
    pages = list(project.get("pages") or [])
    if scope == "page":
        page_id = str(body.get("page_id") or "")
        if not any(str(page.get("id") or "") == page_id for page in pages):
            raise _HttpError(404, "Не найдено")
        if not _page_has_result(state, page_id, skip):
            _mark_queued(state, [page_id])
        job = _submit(state, "translate_page", page_id, {"page_id": page_id, "skip_ready": skip})
        return {"job_id": job.id}
    if scope == "all":
        if not pages:
            raise ValueError("В проекте нет страниц")
        ids = [str(page.get("id") or "") for page in pages]
        queued = [page_id for page_id in ids if not _page_has_result(state, page_id, skip)]
        if queued:
            _mark_queued(state, queued)
        payload = {
            "skip_ready": skip,
            "pages": [
                {
                    "page_id": str(page.get("id") or ""),
                    "source_path": str(page.get("source_path") or ""),
                }
                for page in pages
            ],
        }
        job = _submit(state, "translate_all", "", payload)
        return {"job_id": job.id}
    raise ValueError("Неизвестная область перевода")


def _page_has_result(state: AppState, page_id: str, skip_ready: bool) -> bool:
    """Страница уже с переводом и её просят не трогать."""
    if not skip_ready or not state.project_id or not page_id:
        return False
    try:
        return state.store.image_path(state.project_id, page_id, "result").is_file()
    except (ValueError, OSError):
        return False


def _mark_queued(state: AppState, page_ids: list[str]) -> None:
    project_id = state.project_id or ""
    for page_id in page_ids:
        state.store.update_status(project_id, page_id, status="queued")


def _cancel(state: AppState) -> dict:
    """Стоп: выкинуть всю очередь, снять паузу и записать пустой снимок."""
    state.queue.cancel(None)
    state.queue_pending = False
    if state.project_id:
        project = state.store.open_project(state.project_id)
        for record in project.get("pages") or []:
            page_id = str(record.get("id") or "")
            try:
                current = state.store.page_status(state.project_id, page_id)
            except (FileNotFoundError, ValueError):
                continue
            if current["status"] in ("queued", "running"):
                state.store.update_status(
                    state.project_id,
                    page_id,
                    status="idle",
                    progress=0,
                    stage="",
                    error="",
                )
    _save_queue(state)
    return {"ok": True, **_jobs_view(state)}


def _dialog_directory(state: AppState) -> dict:
    chosen = state.dialogs.pick_directory()
    if chosen is None:
        return {"path": None, "cancelled": True}
    path = Path(chosen)
    state.export_dir = path
    return {"path": str(path)}


def _export(state: AppState, body: dict) -> dict:
    """Папка только из диалога. Чужой ``dest`` в JSON не подставляется."""
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    picked = state.export_dir
    if picked is None:
        raise ValueError("Сначала выберите папку экспорта")
    raw = body.get("dest")
    if isinstance(raw, str) and raw.strip() and _same_path(Path(raw), picked):
        dest = Path(picked)
    else:
        dest = Path(picked)
    dest = dest.resolve()
    page_ids = body.get("page_ids")
    if page_ids is None:
        project = state.store.open_project(state.project_id)
        page_ids = [str(page.get("id") or "") for page in project.get("pages") or []]
    if not isinstance(page_ids, list):
        raise ValueError("page_ids должен быть списком")
    fmt = str(body.get("format") or state.settings.export_format).lower()
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt not in ("png", "jpg"):
        raise ValueError("Неизвестный формат экспорта")
    quality = body.get("jpeg_quality")
    if quality is None:
        quality = state.settings.export_jpeg_quality
    if isinstance(quality, bool) or not isinstance(quality, (int, float)):
        raise ValueError("Некорректное качество JPEG")
    quality = max(1, min(100, int(quality)))
    conflict = str(body.get("conflict") or state.settings.export_conflict)
    if conflict not in ("rename", "overwrite", "skip"):
        raise ValueError("Неизвестный конфликт экспорта")
    content = str(body.get("content") or "result").lower()
    if content not in ("result", "clean", "both"):
        raise ValueError("Неизвестное содержимое экспорта")
    archive = str(body.get("archive") or "folder").lower()
    if archive not in ("folder", "zip", "cbz"):
        raise ValueError("Неизвестный вид архива")
    template = body.get("name_template")
    if template is None or template == "":
        template = "{chapter}/{index:03}_{stem}"
    if not isinstance(template, str):
        raise ValueError("Некорректный шаблон имени")
    only_ready = bool(body.get("only_ready"))
    if archive == "folder":
        target = dest
    else:
        target = dest / f"export.{archive}"
    state.reveal_path = target
    job = _submit(
        state,
        "export",
        "",
        {
            "dest": str(target),
            "page_ids": [str(item) for item in page_ids],
            "format": fmt,
            "jpeg_quality": quality,
            "conflict": conflict,
            "content": content,
            "archive": archive,
            "name_template": template,
            "only_ready": only_ready,
        },
    )
    return {"job_id": job.id}


def _reveal(state: AppState) -> dict:
    target = state.reveal_path
    if target is None and state.project_id:
        target = state.store.project_dir(state.project_id)
    if target is None:
        raise ValueError("Нечего показать")
    state.dialogs.reveal(Path(target))
    return {"ok": True}


def _update_settings(state: AppState, patch: dict) -> dict:
    current = state.settings.to_dict()
    for key, value in patch.items():
        if key in ("api_key", "schema"):
            continue
        if key in current:
            current[key] = value
    state.settings = AppSettings.from_dict(current)
    state.settings.save(state.settings_path)
    return state.settings.to_dict()


def _set_secret(state: AppState, body: dict) -> dict:
    if "api_key" not in body:
        raise ValueError("Нужен api_key")
    value = body.get("api_key")
    if not isinstance(value, str):
        raise ValueError("Нужен api_key")
    if value == "":
        return {"ok": True}
    saved = state.settings.set_api_key(value)
    return {"ok": bool(saved)}


def _check_llm(state: AppState) -> dict:
    result = model_manager.check_llm(state.settings.llm_base_url, get_api_key())
    if result.get("ok"):
        state.llm_status = {
            "ok": True,
            "models": [str(item) for item in result.get("models") or []],
        }
    else:
        state.llm_status = {"ok": False, "models": []}
    payload = dict(result)
    payload["vision"] = False
    return payload


def _download_model(state: AppState, body: dict) -> None:
    kind = str(body.get("kind") or "")
    if kind not in ("detector", "lama", "font"):
        raise ValueError("Неизвестный файл для скачивания")
    dest = model_manager.dest_dir(kind, state.settings.models_dir)

    def progress(done, total) -> None:
        state.fanout(WorkerEvent("model.progress", {
            "kind": kind,
            "done": done,
            "total": total,
            "done_bytes": done,
            "total_bytes": total,
        }))

    model_manager.download(kind, dest, progress)


def _dialog_files(state: AppState) -> dict:
    chosen = [Path(path) for path in (state.dialogs.open_files() or [])]
    existing = [path for path in chosen if path.exists()]
    if not existing:
        payload = _collection(state)
        payload["cancelled"] = True
        return payload
    return _add_paths(state, existing, strict=False)


def _dialog_folder(state: AppState, body: dict | None = None) -> dict:
    """Папка через системный диалог.

    ``pick: true`` только возвращает путь. Иначе страницы верхнего уровня
    добавляются как раньше, а путь всё равно есть в ответе.
    """
    body = body or {}
    chosen = state.dialogs.open_folder()
    if chosen is None or not Path(chosen).exists():
        payload = _collection(state)
        payload["cancelled"] = True
        return payload
    folder = Path(chosen)
    if body.get("pick"):
        return {"path": str(folder), "cancelled": False}
    payload = _add_paths(state, [folder], strict=False)
    payload["path"] = str(folder)
    return payload


def _drop(state: AppState, body: dict) -> dict:
    raw = body.get("paths")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Нужен список paths")
    paths: list[Path] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Путь должен быть строкой")
        paths.append(Path(item))
    return _add_paths(state, paths, strict=True)


def _add_paths(state: AppState, paths: list[Path], *, strict: bool) -> dict:
    if strict:
        missing = [path for path in paths if not path.exists()]
        if missing:
            raise ValueError("Путь не найден")
        prepared = list(paths)
    else:
        prepared = [path for path in paths if path.exists()]
    archives = [path for path in prepared if path.is_file() and is_archive(path)]
    rest = [path for path in prepared if path not in archives]
    usable, warnings = _usable_archives(archives)
    if not usable and not rest and warnings:
        raise NoImagesError(" ".join(warnings))
    usable_keys = {_path_key(path) for path in usable}
    with state._lock:
        if usable or rest:
            if state.project_id is None:
                created = state.store.create_project(
                    _project_title(prepared),
                    "auto",
                    state.settings.target_lang,
                )
                state.project_id = str(created["id"])
            for path in prepared:
                if _path_key(path) in usable_keys:
                    state.store.import_path(
                        state.project_id,
                        path,
                        chapter_mode="subdir",
                    )
                elif path.is_file() and is_archive(path):
                    continue
                else:
                    state.store.add_sources(state.project_id, [path])
            _remember_project(state, state.project_id)
        payload = _collection(state)
    if warnings:
        payload["warnings"] = warnings
    return payload


def _usable_archives(archives: list[Path]) -> tuple[list[Path], list[str]]:
    """Архивы с картинками и тексты про пустые.

    Проверка до создания проекта: пустой архив не оставляет пустой проект,
    если кроме него ничего нет.
    """
    usable: list[Path] = []
    warnings: list[str] = []
    for archive in archives:
        try:
            archive_images(archive)
        except NoImagesError as exc:
            warnings.append(str(exc))
            continue
        usable.append(archive)
    return usable, warnings


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _project_title(paths: list[Path]) -> str:
    for path in paths:
        if path.is_dir():
            name = path.name.strip()
            return name or "Проект"
        if is_archive(path):
            name = path.stem.strip()
            return name or "Проект"
    return "Проект"


def _remember_project(state: AppState, project_id: str) -> None:
    items = [project_id]
    for item in state.settings.recent_projects:
        if item != project_id and item not in items:
            items.append(item)
    state.settings.recent_projects = items[:10]
    state.settings.save(state.settings_path)


def _remove_pages(state: AppState, body: dict) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    raw = body.get("page_ids")
    if not isinstance(raw, list):
        raise ValueError("Нужен список page_ids")
    state.store.remove_pages(state.project_id, [str(item) for item in raw])
    return _collection(state)


def _open_recent(state: AppState, body: dict) -> dict:
    project_id = str(body.get("id") or "").strip()
    if not project_id:
        raise ValueError("Нужен id")
    project = state.store.open_project(project_id)
    with state._lock:
        state.project_id = str(project.get("id") or project_id)
        _remember_project(state, state.project_id)
        payload = _collection(state)
    return payload


def _recent_view(state: AppState) -> list[dict]:
    items = []
    for project_id in state.settings.recent_projects:
        try:
            project = state.store.open_project(project_id)
        except (FileNotFoundError, ValueError, OSError):
            items.append({"id": project_id, "name": "", "path": ""})
            continue
        path = ""
        for page in project.get("pages") or []:
            source = str(page.get("source_path") or "")
            if source:
                path = str(Path(source).parent)
                break
        items.append({
            "id": str(project.get("id") or project_id),
            "name": str(project.get("name") or ""),
            "path": path,
        })
    return items


def _submit(state: AppState, kind: str, page_id: str, payload: dict | None = None):
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    data = dict(payload or {})
    data["store_root"] = str(state.store.root)
    job = state.queue.submit(
        kind,
        state.project_id,
        page_id=page_id,
        settings=state.settings,
        payload=data,
    )
    _save_queue(state)
    return job


def _save_queue(state: AppState) -> None:
    try:
        state.queue.save(state.queue_path())
    except OSError:
        logger.exception("Не удалось сохранить очередь")


def _jobs_view(state: AppState) -> dict:
    """Пауза, незаконченные задания и факт восстановления при старте."""
    snap = state.queue.snapshot()
    statuses = snap.get("statuses") or {}
    unfinished = bool(snap.get("batch") or snap.get("edits")) or any(
        status in ("queued", "running") for status in statuses.values()
    )
    return {
        "paused": bool(state.queue.paused),
        "unfinished": unfinished,
        "restored": bool(state.queue_pending),
    }


def _pause_jobs(state: AppState) -> dict:
    state.queue.pause()
    _save_queue(state)
    return {"ok": True, **_jobs_view(state)}


def _resume_jobs(state: AppState) -> dict:
    state.queue.resume()
    _save_queue(state)
    return {"ok": True, **_jobs_view(state)}


def _retry_errors(state: AppState) -> dict:
    """Снова поставить задания со статусом error через очередь."""
    jobs = state.queue.retry_failed()
    if state.project_id:
        for job in jobs:
            if job.project_id != state.project_id:
                continue
            page_ids: list[str] = []
            if job.page_id:
                page_ids.append(job.page_id)
            raw_pages = job.payload.get("pages")
            if isinstance(raw_pages, list):
                for item in raw_pages:
                    if isinstance(item, dict) and item.get("page_id"):
                        page_ids.append(str(item["page_id"]))
            for page_id in page_ids:
                try:
                    state.store.update_status(
                        state.project_id,
                        page_id,
                        status="queued",
                        error="",
                    )
                except (FileNotFoundError, ValueError, OSError):
                    continue
    _save_queue(state)
    return {"ok": True, "job_ids": [job.id for job in jobs], **_jobs_view(state)}


def _import_sources(state: AppState, body: dict) -> dict:
    raw = body.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Нужен path")
    path = Path(raw.strip())
    if not path.exists():
        raise ValueError("Путь не найден")
    if path.is_file() and is_archive(path):
        archive_images(path)
    mode = str(body.get("chapter_mode") or "subdir")
    if mode not in ("subdir", "flat"):
        raise ValueError("Неизвестный режим глав")
    recursive = bool(body.get("recursive"))
    with state._lock:
        if state.project_id is None:
            created = state.store.create_project(
                _project_title([path]),
                "auto",
                state.settings.target_lang,
            )
            state.project_id = str(created["id"])
        added = state.store.import_path(
            state.project_id,
            path,
            recursive=recursive,
            chapter_mode=mode,
        )
        _remember_project(state, state.project_id)
        payload = _collection(state)
    payload["added"] = [str(item.get("id") or "") for item in added]
    return payload


def _get_glossary(state: AppState) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    return {"glossary": state.store.glossary_view(state.project_id)}


def _put_glossary(state: AppState, body: dict) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    raw = body.get("glossary")
    if not isinstance(raw, list):
        raise ValueError("Нужен список глоссария")
    state.store.write_glossary(state.project_id, raw)
    return {"glossary": state.store.glossary_view(state.project_id)}


def _get_styles(state: AppState) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    return {"styles": state.store.read_styles(state.project_id)}


def _put_styles(state: AppState, body: dict) -> dict:
    if not state.project_id:
        raise ValueError("Нет открытого проекта")
    raw = body.get("styles")
    if not isinstance(raw, list):
        raise ValueError("Нужен список стилей")
    return {"styles": state.store.write_styles(state.project_id, raw)}


_font_faces: list | None = None
_font_lock = threading.Lock()


def _font_faces_cached() -> list:
    """Один обход каталога на процесс. Ошибка чтения даёт пустой список."""
    global _font_faces
    with _font_lock:
        if _font_faces is None:
            try:
                from src.components.font_catalog import scan_fonts

                _font_faces = scan_fonts()
            except Exception:
                logger.exception("Каталог шрифтов")
                _font_faces = []
        return list(_font_faces)


def _font_list() -> dict:
    from src.components.font_catalog import FontFace

    fonts = []
    for face in _font_faces_cached():
        if not isinstance(face, FontFace):
            continue
        fonts.append(
            {
                "id": face.id,
                "family": face.family,
                "category": face.category,
                "cyrillic": bool(face.cyrillic),
            }
        )
    return {"fonts": fonts}


def _preview_text(query: dict) -> str:
    raw = ""
    values = query.get("text") if query else None
    if values:
        raw = values[0]
    text = str(raw or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        text = "Привет"
    return text[:40]


def _font_preview(font_id: str, query: dict) -> _Result:
    from src.components.font_catalog import find_font

    face = find_font(font_id, _font_faces_cached())
    if face is None:
        raise _HttpError(404, "Шрифт не найден")
    try:
        png = _render_font_png(face.path, _preview_text(query))
    except _HttpError:
        raise
    except Exception as exc:
        logger.exception("Образец шрифта")
        raise _HttpError(400, "Не удалось нарисовать образец") from exc
    return _Result(body=png, content_type="image/png")


def _render_font_png(path: str, text: str) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(path, 48)
    probe = Image.new("RGB", (8, 8), "white")
    draw = ImageDraw.Draw(probe)
    box = draw.textbbox((0, 0), text, font=font)
    width = max(1, min(800, box[2] - box[0] + 24))
    height = max(1, min(400, box[3] - box[1] + 24))
    image = Image.new("RGB", (width, height), (255, 255, 255))
    ImageDraw.Draw(image).text((12 - box[0], 12 - box[1]), text, font=font, fill=(0, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _preview_region(state: AppState, page_id: str, body: dict) -> _Result:
    region_id = _region_id(body.get("region_id"))
    record = _require_page(state, page_id)
    document = state.store.read_document(state.project_id or "", page_id)
    region = next((item for item in document.regions if item.id == region_id), None)
    if region is None:
        raise _HttpError(400, "Регион не найден")
    try:
        png, origin_x, origin_y = _typeset_crop(state, page_id, record, region)
    except _HttpError:
        raise
    except Exception as exc:
        logger.exception("Предпросмотр региона")
        raise _HttpError(400, "Не удалось нарисовать образец") from exc
    return _Result(
        body=png,
        content_type="image/png",
        headers={"X-Offset-X": str(origin_x), "X-Offset-Y": str(origin_y)},
    )


def _open_page_rgb(state: AppState, page_id: str, record: dict):
    """Чистая страница, если она уже есть, иначе оригинал."""
    from PIL import Image

    project_id = state.project_id or ""
    clean = state.store.image_path(project_id, page_id, "clean")
    path = clean if clean.is_file() else Path(str(record.get("source_path") or ""))
    if not path.is_file():
        raise _HttpError(400, "Нет изображения страницы")
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB")
    except _HttpError:
        raise
    except Exception as exc:
        raise _HttpError(400, "Не удалось открыть изображение") from exc


def _typeset_crop(state: AppState, page_id: str, record: dict, region) -> tuple[bytes, int, int]:
    from copy import deepcopy
    from io import BytesIO

    from src.components.typesetter import Typesetter

    image = _open_page_rgb(state, page_id, record)
    region_copy = deepcopy(region)
    if not str(region_copy.translation or "").strip():
        region_copy.translation = str(region_copy.text or "").strip() or "А"
    settings = state.settings
    setter = Typesetter(
        min_font_size=int(getattr(settings, "min_font_size", 10) or 10),
        max_font_size=int(getattr(settings, "max_font_size", 128) or 128),
        lang=str(getattr(settings, "target_lang", "ru") or "ru"),
        stroke_ratio=float(getattr(settings, "text_stroke_ratio", 0) or 0),
        margin_ratio=float(getattr(settings, "text_margin", 0) or 0),
    )
    rendered, _overflow = setter.render(image.copy(), [region_copy], force=True)
    x, y, width, height = (int(value) for value in region.bbox)
    page_w, page_h = rendered.size
    x0 = max(0, min(page_w - 1, x))
    y0 = max(0, min(page_h - 1, y))
    x1 = max(x0 + 1, min(page_w, x + max(width, 1)))
    y1 = max(y0 + 1, min(page_h, y + max(height, 1)))
    crop = rendered.crop((x0, y0, x1, y1))
    buffer = BytesIO()
    crop.save(buffer, format="PNG")
    return buffer.getvalue(), x0, y0


def _apply_sfx_style(state: AppState, page_id: str, region_raw: str) -> dict:
    try:
        from src.components.sfx_style import estimate_style
    except ImportError as exc:
        raise _HttpError(503, "Подбор стиля звука недоступен") from exc
    region_id = _region_id(region_raw)
    record = _require_page(state, page_id)
    project_id = state.project_id or ""
    document = state.store.read_document(project_id, page_id)
    region = next((item for item in document.regions if item.id == region_id), None)
    if region is None:
        raise _HttpError(400, "Регион не найден")
    try:
        image = _original_rgb(record)
        mask = _region_mask(state, page_id, image, region)
        estimated = estimate_style(image, mask)
    except _HttpError:
        raise
    except Exception as exc:
        logger.exception("Подбор стиля звука")
        raise _HttpError(400, "Не удалось подобрать стиль") from exc
    if not isinstance(estimated, dict):
        raise _HttpError(400, "Не удалось подобрать стиль")
    from src.models import TextStyle

    saved = None
    for _attempt in range(2):
        document = state.store.read_document(project_id, page_id)
        region = next((item for item in document.regions if item.id == region_id), None)
        if region is None:
            raise _HttpError(400, "Регион не найден")
        region.style = TextStyle.from_dict(_merge_style(region.style.to_dict(), estimated))
        try:
            saved = state.store.write_document(
                project_id, page_id, document, base_version=int(document.version),
            )
            break
        except VersionConflict:
            saved = None
    if saved is None:
        raise _HttpError(409, "Конфликт версии")
    try:
        state.store.update_status(project_id, page_id, status="edited")
    except (FileNotFoundError, ValueError, OSError):
        logger.exception("Статус страницы после стиля звука")
    found = next((item for item in saved.regions if item.id == region_id), None)
    if found is None:
        raise _HttpError(400, "Регион не найден")
    return found.to_dict()


def _original_rgb(record: dict):
    from PIL import Image
    import numpy as np

    path = Path(str(record.get("source_path") or ""))
    if not path.is_file():
        raise _HttpError(400, "Нет изображения страницы")
    try:
        with Image.open(path) as image:
            image.load()
            return np.array(image.convert("RGB"))
    except _HttpError:
        raise
    except Exception as exc:
        raise _HttpError(400, "Не удалось открыть изображение") from exc


def _region_mask(state: AppState, page_id: str, image_rgb, region):
    """Маска букв из сохранённого кадра, иначе прямоугольник рамки."""
    import numpy as np
    from PIL import Image

    height, width = image_rgb.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    x, y, box_w, box_h = (int(value) for value in region.bbox)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + max(box_w, 0)), min(height, y + max(box_h, 0))
    mask_path = state.store.image_path(state.project_id or "", page_id, "mask")
    if mask_path.is_file() and x1 > x0 and y1 > y0:
        try:
            with Image.open(mask_path) as stored:
                stored.load()
                pixels = np.array(stored.convert("L"))
            if pixels.shape[:2] == (height, width):
                mask[y0:y1, x0:x1] = pixels[y0:y1, x0:x1]
        except Exception:
            logger.exception("Маска региона")
    if not mask.any() and x1 > x0 and y1 > y0:
        mask[y0:y1, x0:x1] = 255
    return mask


def _merge_style(current: dict, estimated: dict) -> dict:
    """Цвет и обводка оценки поверх стиля. Угол и искривление не копируем."""
    merged = dict(current)
    for key, value in estimated.items():
        if key in ("rotation", "warp") or value is None:
            continue
        merged[key] = value
    return merged


_REMOTE_EMPTY = {
    "enabled": False,
    "addresses": [],
    "pairing_code": "",
    "devices": [],
    "recent": [],
    "clients": 0,
}


def _remote_status(state: AppState) -> dict:
    remote = getattr(state, "remote_api", None)
    if remote is None:
        return dict(_REMOTE_EMPTY)
    try:
        snapshot = remote.status_snapshot()
    except AttributeError:
        return {
            "enabled": True,
            "addresses": [],
            "pairing_code": "",
            "devices": [],
            "recent": [],
            "clients": 0,
        }
    if not isinstance(snapshot, dict):
        return {
            "enabled": True,
            "addresses": [],
            "pairing_code": "",
            "devices": [],
            "recent": [],
            "clients": 0,
        }
    return snapshot


def _remote_pair(state: AppState) -> dict:
    remote = getattr(state, "remote_api", None)
    if remote is None:
        raise _HttpError(409, "Доступ по сети выключен")
    pairing = getattr(remote, "pairing", None)
    issue = getattr(pairing, "issue_code", None) if pairing is not None else None
    if not callable(issue):
        raise _HttpError(409, "Код подключения недоступен")
    code = issue()
    snapshot = _remote_status(state)
    snapshot["pairing_code"] = code if isinstance(code, str) else str(code or "")
    return snapshot


def _remote_revoke(state: AppState, body: dict) -> dict:
    remote = getattr(state, "remote_api", None)
    if remote is None:
        raise _HttpError(409, "Доступ по сети выключен")
    device_id = body.get("id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Нужен id")
    revoke = getattr(remote, "revoke", None)
    if not callable(revoke):
        raise _HttpError(503, "Отзыв доступа недоступен")
    revoke(device_id.strip())
    return _remote_status(state)


def _image(state: AppState, page_id: str, kind: str) -> _Result:
    if kind not in _IMAGE_KINDS:
        raise _HttpError(404, "Не найдено")
    record = _require_page(state, page_id)
    if kind == "original":
        source = str(record.get("source_path") or "")
        path = Path(source) if source else None
    else:
        path = state.store.image_path(state.project_id or "", page_id, kind)
    if path is None or not path.is_file():
        raise _HttpError(404, "Не найдено")
    content_type = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return _Result(body=path.read_bytes(), content_type=content_type)


def _static(state: AppState, url_path: str, query: dict) -> _Result:
    token = None
    if "k" in query and query["k"]:
        token = query["k"][0]
    cookie = None
    if token is not None:
        if not _same_token(str(token), state.token):
            raise _HttpError(401, "Не авторизован")
        cookie = state.token
    target = _static_target(state.web_root, url_path)
    if target is None:
        raise _HttpError(404, "Не найдено")
    content_type = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return _Result(body=target.read_bytes(), content_type=content_type, cookie=cookie)


def _static_target(web_root: Path, url_path: str) -> Path | None:
    """Файл внутри ``web_root``. ``..`` и каталог ``mockups`` не отдаются."""
    if not url_path.startswith("/") or "\\" in url_path or "\x00" in url_path:
        return None
    if url_path != "/" and url_path.endswith("/"):
        return None
    parts = [part for part in PurePosixPath(url_path).parts if part != "/"]
    if any(part.casefold() == "mockups" for part in parts):
        return None
    root = web_root.resolve()
    current = root
    for part in parts or ["index.html"]:
        if part in (".", "..") or part.casefold() == "mockups" or ":" in part:
            return None
        current = current / part
    try:
        candidate = current.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    relative = candidate.relative_to(root)
    if any(part.casefold() == "mockups" for part in relative.parts):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _stream_events(handler: BaseHTTPRequestHandler, state: AppState) -> None:
    box = state.subscribe()
    handler._ilt_sent = True  # type: ignore[attr-defined]
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.flush()
        while not state._stop.is_set():
            state.broadcast_pending()
            try:
                item = box.get(timeout=_SSE_KEEPALIVE_SEC)
            except queue.Empty:
                handler.wfile.write(b": keep-alive\n\n")
                handler.wfile.flush()
                continue
            if item is None:
                break
            event_type = str(item.get("type") or "message").replace("\r", "").replace("\n", "")
            data = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            handler.wfile.write(f"event: {event_type}\ndata: {data}\n\n".encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
        return
    finally:
        state.unsubscribe(box)


def _send_result(handler: BaseHTTPRequestHandler, result: _Result) -> None:
    if result.body is not None and result.payload is None:
        _send_bytes(
            handler,
            result.body,
            result.status,
            result.content_type or "application/octet-stream",
            cookie=result.cookie,
            extra_headers=result.headers,
        )
        return
    _send_json(handler, result.payload or {}, result.status, cookie=result.cookie)


def _send_json(
    handler: BaseHTTPRequestHandler,
    payload: dict,
    status: int = 200,
    *,
    cookie: str | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _send_bytes(handler, body, status, "application/json; charset=utf-8", cookie=cookie)


def _send_bytes(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    status: int,
    content_type: str,
    *,
    cookie: str | None = None,
    extra_headers: dict | None = None,
) -> None:
    if getattr(handler, "_ilt_sent", False):
        return
    handler._ilt_sent = True  # type: ignore[attr-defined]
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    for name, value in (extra_headers or {}).items():
        handler.send_header(str(name), str(value))
    if cookie:
        handler.send_header("Set-Cookie", _cookie_header(cookie))
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()
