"""Быстрая сессия: файлы на ПК, перевод через LAN API расширения."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from src.app.store import ProjectStore
from src.app.quick_remote import QuickRemoteClient, RemoteCancelled, server_url

_FORMATS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
_BUSY = {"queued", "running"}
_REPORT_SETTINGS = ("source_lang", "target_lang", "quick_server_url")
logger = logging.getLogger("ilt.app.quick")


class QuickSession:
    """Сессия живёт с хостом; её проекты не попадают в список редактора."""

    def __init__(self, state):
        self.state = state
        self.store = ProjectStore(state.store.root / "quick")
        self.project_id = ""
        self.items: list[dict] = []
        self.selected_id = ""
        self.lock = threading.RLock()
        self._pending = []
        self._runs = {}
        self._thread = None
        self._closed = False
        self.client_factory = QuickRemoteClient

    def route(self, method: str, path: str, body: dict):
        from src.app.server import _HttpError, _Result, _need_method

        with self.lock:
            action = path.removeprefix("/api/quick/")
            if action == "session":
                _need_method(method, "GET")
                return _Result(self.snapshot())
            if action.startswith("image/"):
                _need_method(method, "GET")
                parts = action.split("/")
                if len(parts) != 3 or parts[2] not in {"original", "result"}:
                    raise _HttpError(404, "Изображение не найдено")
                item = self._item(parts[1])
                source = self._image(item, parts[2])
                with Image.open(source) as image:
                    output = io.BytesIO()
                    image.convert("RGB").save(output, "PNG")
                return _Result(body=output.getvalue(), content_type="image/png")
            _need_method(method, "POST")
            if action == "accept":
                return _Result(self.accept(body.get("paths")))
            if action == "server":
                return _Result(self._configure_server(body))
            item = self._item(body.get("id"))
            if action == "select":
                self.selected_id = item["id"]
            elif action == "cancel":
                self._cancel(item)
            elif action == "retry":
                if self._view(item)["status"] in _BUSY:
                    raise _HttpError(409, "Изображение уже в очереди")
                self._enqueue(item, fresh=True)
            elif action == "remove":
                self._cancel(item)
                index = self.items.index(item)
                self.items.remove(item)
                if self.selected_id == item["id"]:
                    self.selected_id = self.items[min(index, len(self.items) - 1)]["id"] if self.items else ""
            elif action == "save":
                return _Result(self._save(item, body))
            elif action == "bug-report":
                return _Result(self._report(item, body.get("note")))
            elif action == "editor":
                return _Result(self._editor(item))
            else:
                raise _HttpError(404, "Неизвестное действие быстрого окна")
            return _Result(self.snapshot())

    def _item(self, item_id) -> dict:
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise FileNotFoundError("Элемент быстрого перевода не найден")

    def accept(self, paths) -> dict:
        if not isinstance(paths, list) or not paths or len(paths) > 1000 or any(not isinstance(x, str) for x in paths):
            raise ValueError("Нужен непустой список путей (не более 1000)")
        for raw in paths:
            path = Path(raw).absolute()
            try:
                key = os.path.normcase(str(path.resolve()))
            except (OSError, ValueError):
                key = os.path.normcase(str(path))
            existing = next((x for x in self.items if x["key"] == key), None)
            if existing is not None:
                self.selected_id = existing["id"]
                continue
            item = {"id": uuid.uuid4().hex, "key": key, "source_path": str(path),
                    "name": path.name, "page_id": "", "job_id": "", "status": "error",
                    "progress": 0, "stage": "", "error": "", "warnings": [], "settings": {}}
            self.items.append(item)
            self.selected_id = item["id"]
            self._enqueue(item)
        return self.snapshot()

    def _token(self) -> str:
        try:
            lines = (self.state.store.root / "quick-server-token.txt").read_text(encoding="utf-8").splitlines()
            # Не пересылать Bearer другому адресу после ручной правки настроек.
            if len(lines) == 2 and lines[0] == self.state.settings.quick_server_url:
                return lines[1].strip()
            return ""
        except OSError:
            return ""

    def _configure_server(self, body: dict) -> dict:
        from src.app.server import _HttpError

        if self.snapshot()["busy"]:
            raise _HttpError(409, "Сначала дождитесь перевода или отмените очередь")
        url = server_url(body.get("url"))
        code = str(body.get("code") or "").strip()
        token = self.client_factory(url).pair(code) if code else ""
        previous = self.state.settings.quick_server_url
        # Сырой Bearer хранится отдельно от JSON настроек и снимков заданий.
        if code or url != previous:
            path = self.state.store.root / "quick-server-token.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(f"{url}\n{token}" if token else "", encoding="utf-8")
            temporary.replace(path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        self.state.settings.quick_server_url = url
        self.state.settings.save(self.state.settings_path)
        return self.snapshot()

    def _enqueue(self, item: dict, *, fresh=False) -> None:
        item.update(job_id="", remote_id="", error="", progress=0, stage="", warnings=[])
        try:
            path = Path(item["source_path"])
            if path.suffix.lower() not in _FORMATS:
                raise ValueError("Неподдерживаемый формат. Нужен PNG, JPG/JPEG, BMP или TIFF")
            if not path.is_file():
                raise ValueError("Файл исчез или не найден")
            with Image.open(path) as image:
                image.verify()
            settings = {"source_lang": "auto", "target_lang": self.state.settings.target_lang,
                        "quick_server_url": server_url(self.state.settings.quick_server_url)}
            item["settings"] = settings
            token = self._token()
            if not token:
                raise ValueError("Настройте сопряжение с сервером: ПКМ → Сервер…")
            if not self.project_id:
                project = self.store.create_project("Быстрый перевод", "auto", settings["target_lang"])
                self.project_id = project["id"]
            if not item["page_id"]:
                page = self.store.append_portable_page(self.project_id, path)
                item["page_id"] = page["id"]
            task_id = uuid.uuid4().hex
            cancel = threading.Event()
            item.update(job_id=task_id, settings=settings, status="queued")
            self._runs[task_id] = cancel
            self._pending.append((item, task_id, cancel, token, fresh))
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True, name="ilt-quick-client")
                self._thread.start()
        except Exception as exc:
            item.update(status="error", error=str(exc))

    def _work(self):
        while True:
            with self.lock:
                if not self._pending or self._closed:
                    self._thread = None
                    return
                item, task_id, cancel, token, fresh = self._pending.pop(0)
                if cancel.is_set():
                    self._runs.pop(task_id, None)
                    continue
                settings = dict(item["settings"])
                item["status"] = "running"

            def progress(view):
                with self.lock:
                    if item["job_id"] != task_id or cancel.is_set():
                        return
                    item.update(status=view.get("status", "running"),
                                progress=max(0, min(100, int(view.get("progress") or 0))),
                                stage=str(view.get("stage") or ""), label=str(view.get("label") or ""),
                                remote_id=view.get("remote_id", ""), server_version=view.get("server_version", ""),
                                server_position=view.get("position", 0),
                                server_settings=(view.get("diagnostics") or {}).get("settings"))
                    # До скачивания PNG done ещё считается активной обработкой.
                    if item["status"] == "done":
                        item["status"] = "running"

            try:
                client = self.client_factory(settings["quick_server_url"], token)
                logger.info("Быстрый перевод %s: сервер %s", task_id, settings["quick_server_url"])
                png, remote = client.translate(Path(item["source_path"]), settings["target_lang"],
                    fresh=fresh, cancel=cancel, progress=progress)
                with self.lock:
                    if item["job_id"] == task_id and not cancel.is_set():
                        with Image.open(io.BytesIO(png)) as result:
                            self.store.save_image(self.project_id, item["page_id"], "result", result.convert("RGB"))
                        diagnostics = remote.get("diagnostics") or {}
                        warnings = list(diagnostics.get("warnings") or remote.get("warnings") or [])
                        if "текст не найден" in str(remote.get("label") or "").lower():
                            warnings.append("Текст не найден")
                        item.update(status="done", progress=100, error="", warnings=list(dict.fromkeys(warnings)),
                                    server_version=remote.get("server_version", ""),
                                    result_target_lang=settings["target_lang"],
                                    server_settings=diagnostics.get("settings"))
                        logger.info("Быстрый перевод %s: готово", task_id)
            except RemoteCancelled:
                with self.lock:
                    if item["job_id"] == task_id:
                        item["status"] = "cancelled"
            except Exception as exc:
                with self.lock:
                    if item["job_id"] == task_id and not cancel.is_set():
                        item.update(status="error", error=str(exc))
                        logger.warning("Быстрый перевод %s: %s", task_id, self._redact(str(exc)))
            finally:
                with self.lock:
                    self._runs.pop(task_id, None)

    def _view(self, item: dict) -> dict:
        view = {k: v for k, v in item.items() if k not in {"key", "settings"}}
        view["has_result"] = bool(item["page_id"] and self._image(item, "result").is_file())
        view["target_lang"] = item.get("result_target_lang") or item["settings"].get("target_lang", self.state.settings.target_lang)
        return view

    def snapshot(self) -> dict:
        with self.lock:
            views = [self._view(x) for x in self.items]
            position = 0
            for view in views:
                if view["status"] == "queued":
                    position = max(position + 1, int(view.get("server_position") or 0))
                    view["queue_position"] = position
            return {"items": views, "selected_id": self.selected_id,
                    "busy": bool(self._runs) or any(x["status"] in _BUSY for x in views),
                    "server": {"url": self.state.settings.quick_server_url, "paired": bool(self._token())}}

    def _cancel(self, item: dict) -> None:
        cancel = self._runs.get(item["job_id"])
        if cancel is not None:
            cancel.set()
            item["status"] = "cancelled"

    def close(self):
        with self.lock:
            self._closed = True
            for cancel in self._runs.values():
                cancel.set()

    def _image(self, item: dict, kind: str) -> Path:
        if kind == "original":
            return Path(item["source_path"])
        if not item["page_id"]:
            raise ValueError("Результат ещё не готов")
        return self.store.image_path(self.project_id, item["page_id"], "result")

    def _save(self, item: dict, body: dict) -> dict:
        from src.app.server import _HttpError

        raw = body.get("path")
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError("Выберите абсолютный путь сохранения")
        dest = Path(raw)
        if dest.suffix.lower() != ".png":
            raise ValueError("Результат сохраняется в PNG")
        for source in self.items:
            original = Path(source["source_path"])
            if dest.resolve() == original.resolve() or (dest.exists() and original.exists() and os.path.samefile(dest, original)):
                raise ValueError("Нельзя перезаписать оригинал")
        source = self._image(item, "result")
        if not source.is_file():
            raise ValueError("Результат ещё не готов")
        if dest.exists() and body.get("overwrite") is not True:
            raise _HttpError(409, "Файл уже существует. Подтвердите замену")
        if body.get("overwrite") is True:
            temporary = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(dest)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            try:
                with dest.open("xb") as output, source.open("rb") as incoming:
                    shutil.copyfileobj(incoming, output)
            except FileExistsError as exc:
                raise _HttpError(409, "Файл уже существует. Подтвердите замену") from exc
        return {"path": str(dest)}

    def _redact(self, value: str) -> str:
        from src.app.settings import get_api_key

        text = str(value)
        for secret in (get_api_key(), self.state.token, self._token()):
            if secret:
                text = text.replace(secret, "[скрыто]")

        def clean_url(match):
            try:
                parts = urlsplit(match.group())
                host = parts.netloc.rsplit("@", 1)[-1]
                return urlunsplit((parts.scheme, host, parts.path, "", ""))
            except ValueError:
                return "[адрес скрыт]"

        text = re.sub(r"https?://[^\s\"<>]+", clean_url, text)
        text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[скрыто]", text)
        return re.sub(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,\"']+", r"\1[скрыто]", text)

    def _report(self, item: dict, note) -> dict:
        from src.app import __version__

        if not isinstance(note, str) or not note.strip() or len(note.strip()) > 4000:
            raise ValueError("Опишите проблему: от 1 до 4000 символов")
        folder = self.state.store.root / "bug-reports" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        snapshot = self._view(item)
        snapshot["settings"] = {key: item["settings"].get(key, getattr(self.state.settings, key, "")) for key in _REPORT_SETTINGS}
        snapshot.update(note=note.strip(), version=__version__, processing="remote-v1",
                        server_settings_available=bool(item.get("server_settings")),
                        server_settings_note="Параметры пайплайна управляются сервером; старые версии v1 API не отдают снимок")
        def redact_tree(value):
            if isinstance(value, dict):
                return {key: redact_tree(raw) for key, raw in value.items()}
            if isinstance(value, list):
                return [redact_tree(raw) for raw in value]
            return self._redact(value) if isinstance(value, str) else value

        (folder / "report.json").write_text(json.dumps(redact_tree(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "note.txt").write_text(self._redact(note.strip()) + "\n", encoding="utf-8")
        original = Path(item["source_path"])
        if original.is_file():
            try:
                shutil.copyfile(original, folder / ("original" + original.suffix.lower()))
            except OSError:
                pass
        if snapshot["has_result"]:
            shutil.copyfile(self._image(item, "result"), folder / "result.png")
        log = self.state.store.root / "logs/app.log"
        if item["job_id"] and log.is_file():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 1024 * 1024))
                tail = stream.read().decode("utf-8", errors="replace")
            lines = [line for line in tail.splitlines() if item["job_id"] in line][-200:]
            if lines:
                (folder / "task.log").write_text(self._redact("\n".join(lines)) + "\n", encoding="utf-8")
        return {"path": str(folder)}

    def _editor(self, item: dict) -> dict:
        from src.app.server import _collection, _remember_project

        if self._view(item)["status"] in _BUSY:
            raise ValueError("Дождитесь результата или отмените перевод")
        state = self.state
        with state._lock:
            project = state.store.create_project(Path(item["name"]).stem,
                item["settings"].get("source_lang", state.settings.source_lang),
                item["settings"].get("target_lang", state.settings.target_lang))
            original = Path(item["source_path"])
            copy = state.store.project_dir(project["id"]) / ("original" + original.suffix.lower())
            shutil.copyfile(original, copy)
            document = self.store.read_document(self.project_id, item["page_id"]).to_dict() if item["page_id"] else None
            page = state.store.append_portable_page(project["id"], copy, name=item["name"], document=document)
            if item["page_id"]:
                artifacts = {kind: self.store.image_path(self.project_id, item["page_id"], kind)
                             for kind in ("result", "clean", "mask")}
                state.store.restore_portable_artifacts(project["id"], page["id"], artifacts)
                if artifacts["result"].is_file():
                    state.store.update_status(project["id"], page["id"], status="done", progress=100)
            state.project_id = project["id"]
            state.package_path = None
            state.package_dirty = True
            _remember_project(state, state.project_id)
            return _collection(state)
