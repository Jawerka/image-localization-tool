"""Локальный HTTP API: cookie, диалоги, задания на FakeWorker. Без сети и моделей."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import types
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from src.app import __version__
from src.app.dialogs import DialogBridge
from src.app.document import PageDocument
from src.app.jobs import JobQueue
from src.app.server import AppState, serve
from src.app.settings import AppSettings, get_api_key
from src.app.store import ProjectStore
from src.app.worker import FakeWorker
from src.models import TextRegion


class ProbeWorker(FakeWorker):
    """Запоминает статус страницы в момент submit, до синхронного выполнения."""

    def __init__(self, store: ProjectStore):
        super().__init__(store, synchronous=True)
        self.status_at_submit: list[tuple[str, str]] = []

    def submit(self, job):
        if self.store is not None and job.page_id and job.kind == "translate_page":
            status = self.store.page_status(job.project_id, job.page_id)["status"]
            self.status_at_submit.append((job.kind, status))
        super().submit(job)


class ScriptedDialogs(DialogBridge):
    def __init__(self):
        self.files: list[Path] = []
        self.folder: Path | None = None
        self.directory: Path | None = None
        self.revealed: list[Path] = []
        self.logs = 0

    def open_files(self) -> list[Path]:
        return list(self.files)

    def open_folder(self) -> Path | None:
        return self.folder

    def pick_directory(self) -> Path | None:
        return self.directory

    def reveal(self, path: Path) -> None:
        self.revealed.append(Path(path))

    def open_log(self) -> None:
        self.logs += 1


def _install_keyring(monkeypatch):
    """Как в test_app_settings: keyring не ходит в хранилище Windows."""
    bag: dict = {}
    module = types.ModuleType("keyring")

    def get_password(service, username):
        return bag.get((service, username))

    def set_password(service, username, value):
        bag[(service, username)] = value

    def delete_password(service, username):
        bag.pop((service, username), None)

    module.get_password = get_password
    module.set_password = set_password
    module.delete_password = delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)
    return bag


def _header_values(headers, name: str) -> list[str]:
    return [value for key, value in headers if key.lower() == name.lower()]


def _same_path(left, right) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


class Api:
    def __init__(self, state: AppState, port: int, store: ProjectStore, worker: ProbeWorker, dialogs: ScriptedDialogs, settings_path: Path):
        self.state = state
        self.port = port
        self.store = store
        self.worker = worker
        self.dialogs = dialogs
        self.settings_path = settings_path

    def call(self, method, path, body=None, *, cookie=True, host=None, origin=None):
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin is not None:
            headers["Origin"] = origin
        if cookie is True:
            headers["Cookie"] = f"ilt_session={self.state.token}"
        elif cookie:
            headers["Cookie"] = cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, response.getheaders(), raw
        finally:
            conn.close()

    def json(self, method, path, body=None, **kwargs):
        status, headers, raw = self.call(method, path, body, **kwargs)
        text = raw.decode("utf-8")
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError as exc:
            raise AssertionError(f"Не JSON, статус {status}: {text[:500]}") from exc
        return status, headers, payload


def _wait_until_up(port: int) -> None:
    deadline = time.time() + 3
    last_error = None
    while time.time() < deadline:
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=0.3)
            conn.request("GET", "/api/bootstrap", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            response.read()
            status = response.status
            conn.close()
            if status == 401:
                return
            last_error = f"статус {status}"
        except OSError as exc:
            last_error = exc
            time.sleep(0.02)
    raise RuntimeError(f"Сервер не поднялся: {last_error}")


def _api(tmp_path, monkeypatch):
    _install_keyring(monkeypatch)
    web = tmp_path / "web"
    (web / "css").mkdir(parents=True)
    (web / "index.html").write_text("ILT_INDEX_OK", encoding="utf-8")
    (web / "css" / "base.css").write_text("body{color:red}", encoding="utf-8")
    (web / "mockups").mkdir()
    (web / "mockups" / "secret.html").write_text("ILT_MOCKUP_SECRET", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("ILT_OUTSIDE_SECRET", encoding="utf-8")

    store = ProjectStore(tmp_path / "store")
    settings_path = tmp_path / "settings.json"
    settings = AppSettings(source_lang="en", target_lang="ru")
    worker = ProbeWorker(store)
    dialogs = ScriptedDialogs()
    state = AppState(
        settings=settings,
        settings_path=settings_path,
        settings_warnings=["Файл настроек обновлён"],
        store=store,
        queue=JobQueue(worker),
        dialogs=dialogs,
        web_root=web,
    )
    server, port = serve(state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        _wait_until_up(port)
    except Exception:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        raise
    api = Api(state, port, store, worker, dialogs, settings_path)
    return api, server, thread


def _stop(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def _add_page(api: Api, directory: Path, name: str = "page.png"):
    image = directory / name
    Image.new("RGB", (24, 16), "white").save(image)
    api.dialogs.files = [image]
    status, _, payload = api.json("POST", "/api/dialog/files", {})
    assert status == 200, payload
    return payload, image


@pytest.fixture
def api(tmp_path, monkeypatch):
    client, server, thread = _api(tmp_path, monkeypatch)
    try:
        yield client
    finally:
        _stop(server, thread)


def test_dialog_bridge_is_inert(tmp_path):
    bridge = DialogBridge()
    assert bridge.open_files() == []
    assert bridge.open_folder() is None
    assert bridge.pick_directory() is None
    bridge.reveal(tmp_path)
    bridge.open_log()


def test_bootstrap_requires_cookie(api: Api):
    status, _, payload = api.json("GET", "/api/bootstrap", cookie=False)
    assert status == 401
    assert payload["error"]

    status, _, payload = api.json("GET", "/api/bootstrap", cookie="ilt_session=not-the-token")
    assert status == 401

    status, _, payload = api.json("GET", "/api/bootstrap")
    assert status == 200
    assert set(payload) == {
        "version",
        "settings",
        "settings_warning",
        "project",
        "pages",
        "llm",
        "device",
        "models_ready",
        "busy",
        "recent",
        "has_api_key",
        "paths",
    }
    assert payload["version"] == __version__
    assert payload["settings_warning"] == "Файл настроек обновлён"
    assert payload["project"] is None
    assert payload["pages"] == []
    assert payload["llm"] == {"ok": False, "models": []}
    assert payload["device"] == "auto"
    assert payload["busy"] is False
    assert payload["recent"] == []
    assert payload["has_api_key"] is False
    assert payload["paths"]["settings"] == str(api.settings_path)
    assert payload["paths"]["data"] == str(api.store.root)
    assert isinstance(payload["models_ready"], bool)
    assert "api_key" not in payload["settings"]

    status, _, _ = api.json("GET", "/api/events", cookie=False)
    assert status == 401


def test_llm_probe_sends_status_after_check(api: Api, monkeypatch):
    """Пока проверка идёт, bootstrap не врёт «недоступен». Потом SSE ok: true."""
    started = threading.Event()
    release = threading.Event()

    def slow_check(url, key=""):
        started.set()
        release.wait(3)
        return {"ok": True, "models": ["demo"], "reason": ""}

    monkeypatch.setattr("src.app.model_manager.check_llm", slow_check)
    api.state.settings.llm_base_url = "http://127.0.0.1:9/v1"
    box = api.state.subscribe()
    api.state._start_llm_probe()
    assert started.wait(2)
    status, _, payload = api.json("GET", "/api/bootstrap")
    assert status == 200
    assert payload["llm"] == {"ok": None, "models": []}
    release.set()
    event = box.get(timeout=3)
    assert event["type"] == "llm.status"
    assert event["payload"]["ok"] is True
    assert event["payload"]["models"] == ["demo"]
    assert api.state.llm_status["ok"] is True


def test_host_and_origin(api: Api):
    status, _, payload = api.json("GET", "/api/bootstrap", host="evil.example")
    assert status == 403
    assert payload["error"]

    status, _, payload = api.json("GET", "/api/bootstrap", origin="http://evil.example")
    assert status == 403

    status, _, payload = api.json("GET", "/api/bootstrap", host=f"localhost:{api.port}")
    assert status == 200
    assert payload["version"] == __version__

    status, _, payload = api.json(
        "GET",
        "/api/bootstrap",
        origin=f"http://127.0.0.1:{api.port}",
    )
    assert status == 200
    status, _, payload = api.json(
        "GET",
        "/api/bootstrap",
        origin=f"http://localhost:{api.port}",
    )
    assert status == 200


def test_session_sets_cookie(api: Api):
    status, headers, raw = api.call("GET", "/?k=wrong-token", cookie=False)
    assert status == 401
    assert _header_values(headers, "Set-Cookie") == []
    assert b"ILT_INDEX_OK" not in raw

    status, headers, raw = api.call("GET", "/?k=" + quote(api.state.token, safe=""), cookie=False)
    assert status == 200
    assert raw == b"ILT_INDEX_OK"
    assert _header_values(headers, "Location") == []
    cookie = _header_values(headers, "Set-Cookie")
    assert len(cookie) == 1
    assert cookie[0].startswith(f"ilt_session={api.state.token};")
    assert "HttpOnly" in cookie[0]
    assert "SameSite=Strict" in cookie[0]
    assert "Path=/" in cookie[0]

    status, headers, payload = api.json("POST", "/api/session", {"token": "nope"}, cookie=False)
    assert status == 401
    assert _header_values(headers, "Set-Cookie") == []

    status, headers, payload = api.json(
        "POST",
        "/api/session",
        {"token": api.state.token},
        cookie=False,
    )
    assert status == 200
    assert payload == {"ok": True}
    cookie = _header_values(headers, "Set-Cookie")
    assert len(cookie) == 1
    assert "HttpOnly" in cookie[0]
    assert "SameSite=Strict" in cookie[0]
    pair = cookie[0].split(";", 1)[0]
    status, _, payload = api.json("GET", "/api/bootstrap", cookie=pair)
    assert status == 200
    assert payload["version"] == __version__


def test_dialog_files_keeps_original(api: Api, tmp_path):
    payload, image = _add_page(api, tmp_path)
    project = payload["project"]
    assert project["name"] == "Проект"
    assert project["source_lang"] == "auto"
    assert project["target_lang"] == "ru"
    page = payload["pages"][0]
    assert set(page) == {
        "id",
        "name",
        "source_path",
        "chapter",
        "status",
        "progress",
        "stage",
        "error",
        "warnings",
    }
    assert page["name"] == "page.png"
    assert page["status"] == "idle"
    assert _same_path(page["source_path"], image)
    assert image.is_file()
    page_dir = api.store.page_dir(project["id"], page["id"])
    assert not (page_dir / "page.png").exists()
    assert (page_dir / "thumb.jpg").is_file()
    saved = json.loads(api.settings_path.read_text(encoding="utf-8"))
    assert project["id"] in saved["recent_projects"]
    assert "api_key" not in saved

    status, headers, raw = api.call("GET", f"/api/pages/{page['id']}/image/original?v=1")
    assert status == 200
    assert raw == image.read_bytes()
    content_type = _header_values(headers, "Content-Type")[0]
    assert content_type.startswith("image/png")
    assert "no-store" in _header_values(headers, "Cache-Control")[0].lower()


def test_put_translation_submits_typeset(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    project_id = payload["project"]["id"]
    page_id = payload["pages"][0]["id"]
    seeded = api.store.write_document(
        project_id,
        page_id,
        PageDocument(regions=[
            TextRegion(id=1, bbox=(0, 0, 8, 8), text="Hi", translation="Привет", block_type="dialogue"),
        ]),
    )
    document = seeded.to_dict()
    document["regions"][0]["translation"] = "Здравствуй"
    status, _, body = api.json(
        "PUT",
        f"/api/pages/{page_id}/document",
        {"base_version": seeded.version, "document": document},
    )
    assert status == 200
    assert body["plan"] == "typeset"
    assert body["document"]["regions"][0]["translation"] == "Здравствуй"
    jobs = [job for job in api.worker.calls if job.kind == "apply_document"]
    assert len(jobs) == 1
    assert jobs[0].payload["store_root"] == str(api.store.root)
    assert jobs[0].payload["plan"] == "typeset"
    assert jobs[0].payload["base_version"] == body["document"]["version"]
    assert jobs[0].page_id == page_id


def test_put_stale_version_is_conflict(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    project_id = payload["project"]["id"]
    page_id = payload["pages"][0]["id"]
    seeded = api.store.write_document(
        project_id,
        page_id,
        PageDocument(regions=[
            TextRegion(id=1, bbox=(0, 0, 8, 8), text="Hi", translation="Привет", block_type="dialogue"),
        ]),
    )
    status, _, body = api.json(
        "PUT",
        f"/api/pages/{page_id}/document",
        {"base_version": seeded.version - 1, "document": seeded.to_dict()},
    )
    assert status == 409
    assert body["error"]
    assert body["document"]["version"] == seeded.version
    assert api.worker.calls == []
    assert api.store.read_document(project_id, page_id).version == seeded.version


def test_translate_page_queued_then_done(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    project_id = payload["project"]["id"]
    page_id = payload["pages"][0]["id"]
    status, _, body = api.json(
        "POST",
        "/api/jobs/translate",
        {"scope": "page", "page_id": page_id},
    )
    assert status == 200
    assert body["job_id"]
    assert api.worker.status_at_submit == [("translate_page", "queued")]
    assert api.store.page_status(project_id, page_id)["status"] == "done"
    job = next(item for item in api.worker.calls if item.kind == "translate_page")
    assert job.payload["store_root"] == str(api.store.root)
    assert job.page_id == page_id
    assert api.store.read_document(project_id, page_id).regions[0].translation == "Привет"


def test_thumb_and_unknown_image_kind(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    page_id = payload["pages"][0]["id"]
    project_id = payload["project"]["id"]
    thumb = api.store.image_path(project_id, page_id, "thumb")
    status, headers, raw = api.call("GET", f"/api/pages/{page_id}/image/thumb?v=9")
    assert status == 200
    assert raw == thumb.read_bytes()
    assert raw.startswith(b"\xff\xd8")
    assert _header_values(headers, "Content-Type")[0].startswith("image/jpeg")
    assert "no-store" in _header_values(headers, "Cache-Control")[0].lower()

    status, _, body = api.json("GET", f"/api/pages/{page_id}/image/nope")
    assert status == 404
    assert body["error"]
    status, _, body = api.json("GET", f"/api/pages/{page_id}/image/mask?v=1")
    assert status == 404


def test_static_rejects_traversal_and_mockups(api: Api):
    status, _, raw = api.call("GET", "/", cookie=False)
    assert status == 200
    assert raw == b"ILT_INDEX_OK"

    status, _, raw = api.call("GET", "/css/base.css", cookie=False)
    assert status == 200
    assert raw == b"body{color:red}"

    status, _, raw = api.call("GET", "/../secret.txt", cookie=False)
    assert status == 404
    assert b"ILT_OUTSIDE_SECRET" not in raw

    status, _, raw = api.call("GET", "/css/../../secret.txt", cookie=False)
    assert status == 404
    assert b"ILT_OUTSIDE_SECRET" not in raw

    status, _, raw = api.call("GET", "/mockups/secret.html", cookie=False)
    assert status == 404
    assert b"ILT_MOCKUP_SECRET" not in raw


def test_export_requires_dialog_directory(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    page_id = payload["pages"][0]["id"]
    evil = tmp_path / "evil-dir"
    body = {
        "page_ids": [page_id],
        "format": "jpg",
        "jpeg_quality": 80,
        "conflict": "overwrite",
        "dest": str(evil),
    }
    status, _, payload = api.json("POST", "/api/jobs/export", body)
    assert status == 400
    assert payload["error"]
    assert [job for job in api.worker.calls if job.kind == "export"] == []

    chosen = tmp_path / "chosen-export"
    chosen.mkdir()
    api.dialogs.directory = chosen
    status, _, dialog = api.json("POST", "/api/dialog/directory", {})
    assert status == 200
    assert _same_path(dialog["path"], chosen)

    status, _, payload = api.json("POST", "/api/jobs/export", body)
    assert status == 200
    assert payload["job_id"]
    jobs = [job for job in api.worker.calls if job.kind == "export"]
    assert len(jobs) == 1
    assert _same_path(jobs[0].payload["dest"], chosen)
    assert not _same_path(jobs[0].payload["dest"], evil)
    assert jobs[0].payload["store_root"] == str(api.store.root)
    assert jobs[0].payload["page_ids"] == [page_id]
    assert jobs[0].payload["format"] == "jpg"
    assert jobs[0].payload["jpeg_quality"] == 80
    assert jobs[0].payload["conflict"] == "overwrite"


def test_secret_does_not_echo_or_clear_key(api: Api):
    status, _, raw = api.call("POST", "/api/settings/secret", {"api_key": "super-secret"})
    assert status == 200
    assert b"super-secret" not in raw
    payload = json.loads(raw.decode("utf-8"))
    assert payload == {"ok": True}
    assert get_api_key() == "super-secret"

    status, _, payload = api.json("POST", "/api/settings/secret", {"api_key": ""})
    assert status == 200
    assert payload == {"ok": True}
    assert get_api_key() == "super-secret"

    status, _, payload = api.json("PUT", "/api/settings", {"llm_base_url": "http://box/v1"})
    assert status == 200
    assert payload["settings"]["llm_base_url"] == "http://box/v1"
    assert payload["settings"]["theme"] == "system"

    status, _, raw = api.call("PUT", "/api/settings", {"theme": "dark", "api_key": "nope"})
    assert status == 200
    assert b"super-secret" not in raw
    assert b"nope" not in raw
    saved = json.loads(raw.decode("utf-8"))
    assert saved["settings"]["theme"] == "dark"
    assert saved["settings"]["llm_base_url"] == "http://box/v1"
    assert "api_key" not in saved["settings"]
    text = api.settings_path.read_text(encoding="utf-8")
    assert "super-secret" not in text
    assert "nope" not in text
    assert "api_key" not in text
    assert get_api_key() == "super-secret"
    status, _, bootstrap = api.json("GET", "/api/bootstrap")
    assert status == 200
    assert bootstrap["has_api_key"] is True
    assert "super-secret" not in json.dumps(bootstrap)


def test_llm_check_remembers_models_without_network(api: Api, monkeypatch):
    called = {"count": 0}

    def fake_urlopen(request, timeout=0):
        called["count"] += 1
        assert timeout == 10
        assert request.full_url == "http://127.0.0.1:9/v1/models"

        class _Response:
            def read(self):
                return b'{"data":[{"id":"demo-model"}]}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, _, payload = api.json("PUT", "/api/settings", {"llm_base_url": "http://127.0.0.1:9/v1"})
    assert status == 200
    status, _, payload = api.json("POST", "/api/llm/check", {})
    assert status == 200
    assert called["count"] == 1
    assert payload["ok"] is True
    assert payload["vision"] is False
    assert payload["models"] == ["demo-model"]
    status, _, bootstrap = api.json("GET", "/api/bootstrap")
    assert bootstrap["llm"] == {"ok": True, "models": ["demo-model"]}


def test_sse_reads_one_event_then_closes(api: Api, tmp_path):
    payload, _image = _add_page(api, tmp_path)
    page_id = payload["pages"][0]["id"]
    sock = socket.create_connection(("127.0.0.1", api.port), timeout=5)
    try:
        request = (
            f"GET /api/events HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{api.port}\r\n"
            f"Cookie: ilt_session={api.state.token}\r\n"
            f"Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            assert chunk
            buffer += chunk
        status, _, body = api.json(
            "POST",
            "/api/jobs/translate",
            {"scope": "page", "page_id": page_id},
        )
        assert status == 200
        deadline = time.time() + 3
        while b"event:" not in buffer and time.time() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
    finally:
        sock.close()
    text = buffer.decode("utf-8", errors="replace")
    assert "event:" in text, text
    stream = text.split("\r\n\r\n", 1)[1]
    event_type = None
    parsed = None
    for line in stream.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:") and event_type:
            parsed = json.loads(line[len("data:"):].strip())
            break
    assert event_type
    assert parsed is not None
    assert parsed["type"] == event_type
    assert "payload" in parsed


def test_drop_missing_path_is_rejected(api: Api, tmp_path):
    status, _, payload = api.json("POST", "/api/drop", {"paths": [str(tmp_path / "missing.png")]})
    assert status == 400
    assert payload["error"]
    assert api.state.project_id is None


def test_drop_empty_archive_does_not_create_project(api: Api, tmp_path):
    import zipfile

    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", b"no")
    status, _, payload = api.json("POST", "/api/drop", {"paths": [str(archive)]})
    assert status == 400
    assert "переводить нечего" in payload["error"]
    assert api.state.project_id is None


def test_drop_cbz_adds_pages(api: Api, tmp_path):
    import io
    import zipfile

    archive = tmp_path / "vol.cbz"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in ("page10.png", "page2.png"):
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
            bundle.writestr(name, buffer.getvalue())
    status, _, payload = api.json("POST", "/api/drop", {"paths": [str(archive)]})
    assert status == 200, payload
    assert [page["name"] for page in payload["pages"]] == ["page2.png", "page10.png"]


def test_drop_empty_archive_with_image_warns(api: Api, tmp_path):
    import zipfile

    image = tmp_path / "page.png"
    Image.new("RGB", (4, 4), "white").save(image)
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("notes.txt", b"no")
    status, _, payload = api.json("POST", "/api/drop", {"paths": [str(archive), str(image)]})
    assert status == 200, payload
    assert payload["warnings"]
    assert "переводить нечего" in payload["warnings"][0]
    assert [page["name"] for page in payload["pages"]] == ["page.png"]


def test_import_empty_archive_does_not_create_project(api: Api, tmp_path):
    import zipfile

    archive = tmp_path / "empty.cbz"
    zipfile.ZipFile(archive, "w").close()
    status, _, payload = api.json("POST", "/api/import", {"path": str(archive)})
    assert status == 400
    assert "переводить нечего" in payload["error"]
    assert api.state.project_id is None


def test_fonts_preview_region_and_remote_status(api: Api, monkeypatch):
    """Каталог шрифтов, чужая страница и статус сети без remote_api."""
    from src.app import server as app_server

    monkeypatch.setattr("src.components.font_catalog.scan_fonts", lambda *args, **kwargs: [])
    app_server._font_faces = None

    status, _, payload = api.json("GET", "/api/fonts")
    assert status == 200
    assert payload["fonts"] == []

    status, _, payload = api.json(
        "POST",
        "/api/pages/missing-page/preview-region",
        {"region_id": "1"},
    )
    assert status == 404
    assert payload["error"]

    assert getattr(api.state, "remote_api", None) is None
    status, _, payload = api.json("GET", "/api/remote/status")
    assert status == 200
    assert payload == {
        "enabled": False,
        "addresses": [],
        "pairing_code": "",
        "devices": [],
        "recent": [],
        "clients": 0,
    }
