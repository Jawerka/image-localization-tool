"""Контракт серверного редактора: сеть, авторизация и перенос файлов."""

import io
import json
import threading
import zipfile
from http.client import HTTPConnection

import pytest
from PIL import Image

from src.app.jobs import JobQueue
from src.app.server import AppState, serve
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path))
    store = ProjectStore(tmp_path)
    state = AppState(AppSettings(), tmp_path / "settings.json", store,
                     JobQueue(FakeWorker(store)), token="test-token")
    httpd, port = serve(state, host="0.0.0.0", origins=("http://ilt.test",))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None, *, cookie=True, host="ilt.test", origin="http://ilt.test", raw=None):
        headers = {"Host": host, "Origin": origin}
        if cookie:
            headers["Cookie"] = f"ilt_browser_session={cookie}" if isinstance(cookie, str) else "ilt_session=test-token"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    yield state, call
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def png():
    stream = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_browser_auth_and_origin(browser):
    _, call = browser
    assert call("GET", "/api/jobs", cookie=False)[0] == 200
    assert call("GET", "/api/jobs", host="evil.test")[0] == 403
    assert call("GET", "/api/jobs", origin="http://evil.test")[0] == 403
    assert call("GET", "/api/jobs")[0] == 200
    assert call("POST", "/api/session", {"token": "wrong"}, cookie=False)[0] == 200
    status, headers, _ = call("POST", "/api/session", {"token": "test-token"}, cookie=False)
    assert status == 200
    assert "HttpOnly" in headers["Set-Cookie"]


def test_optional_account_http_lifecycle(browser):
    state, call = browser
    assert call("GET", "/api/browser/access", cookie=False)[0] == 200
    body = {"enabled": True, "username": "owner", "password": "password-059-test"}
    status, headers, raw = call("PUT", "/api/browser/access", body, cookie=False)
    assert status == 200, raw
    cookie = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
    assert headers["Set-Cookie"].startswith("ilt_browser_session=")
    assert "password_hash" not in raw.decode() and "salt" not in raw.decode()
    assert call("GET", "/api/jobs", cookie=False)[0] == 401
    assert call("GET", "/api/jobs", cookie=True)[0] == 401
    assert call("POST", "/api/session", {"token": "test-token"}, cookie=False)[0] == 401
    assert call("POST", "/api/session", {"username": "owner", "password": "wrong"}, cookie=False)[0] == 401
    status, headers, _ = call("GET", "/?k=test-token", cookie=False)
    assert status == 200 and "Set-Cookie" not in headers
    assert call("GET", "/?k=wrong", cookie=False)[0] == 200
    status, headers, _ = call("POST", "/api/session", {"username": "owner", "password": "password-059-test"}, cookie=False)
    assert status == 200
    login_cookie = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
    assert call("GET", "/api/jobs", cookie=login_cookie)[0] == 200
    assert call("POST", "/api/import", {"path": "/etc/passwd"}, cookie=login_cookie)[0] == 403
    assert call("GET", "/api/jobs", cookie=login_cookie, origin="http://evil.test")[0] == 403
    assert call("POST", "/api/browser/logout", {}, cookie=login_cookie)[0] == 200
    assert call("GET", "/api/jobs", cookie=login_cookie)[0] == 401
    assert call("PUT", "/api/browser/access", {"enabled": False}, cookie=cookie)[0] == 401
    status, _, raw = call("PUT", "/api/browser/access", {"enabled": False, "current_password": "password-059-test"}, cookie=cookie)
    assert status == 200, raw
    assert call("GET", "/api/jobs", cookie=False)[0] == 200
    from src.app.web_access import WebAccess
    assert WebAccess(state.settings_path.parent).status()["enabled"] is False


def test_legacy_tokens_do_not_enable_protection(browser, monkeypatch):
    state, call = browser
    monkeypatch.setenv("ILT_WEB_TOKEN", "legacy-token-value")
    (state.settings_path.parent / "web.token").write_text("corrupt")
    assert call("GET", "/api/jobs", cookie=False)[0] == 200


def test_anonymous_sse_is_closed_even_after_off_on_off(browser):
    state, _ = browser
    conn = HTTPConnection("127.0.0.1", state.port, timeout=4)
    conn.request("GET", "/api/events", headers={"Host": "ilt.test", "Origin": "http://ilt.test"})
    response = conn.getresponse()
    assert response.status == 200
    _, token = state.web_access.update({"enabled": True, "username": "owner", "password": "password-059-test"})
    state.web_access.update({"enabled": False, "current_password": "password-059-test"}, token)
    # Соединение завершается по поколению, хотя общий доступ уже снова открыт.
    response.read()
    conn.close()


def test_partial_json_request_does_not_lock_other_editor_requests(browser, monkeypatch):
    state, call = browser
    import src.app.server as server
    reading = threading.Event()
    original_read = server._read_json
    def read(handler):
        if handler.path == "/api/settings":
            reading.set()
        return original_read(handler)
    monkeypatch.setattr(server, "_read_json", read)
    slow = HTTPConnection("127.0.0.1", state.port, timeout=3)
    slow.putrequest("PUT", "/api/settings", skip_host=True)
    slow.putheader("Host", "ilt.test")
    slow.putheader("Origin", "http://ilt.test")
    slow.putheader("Content-Type", "application/json")
    slow.putheader("Content-Length", "1000")
    slow.endheaders()
    slow.send(b'{')
    try:
        assert reading.wait(2)
        assert call("GET", "/api/jobs", cookie=False)[0] == 200
    finally:
        slow.send(b'}' + b' ' * 998)
        slow.getresponse().read()
        slow.close()


@pytest.mark.parametrize("path", ["/api/drop", "/api/import", "/api/dialog/files",
    "/api/dialog/directory", "/api/project/package/load", "/api/project/package/save",
    "/api/preparation/location", "/api/preparation/verify", "/api/runtime/download", "/api/models/download"])
def test_browser_rejects_host_paths(browser, path):
    _, call = browser
    assert call("POST", path, {"path": "C:/private", "paths": ["/etc/passwd"]})[0] == 403


def test_browser_rejects_setting_paths(browser):
    _, call = browser
    assert call("PUT", "/api/settings", {"models_dir": "/etc"})[0] == 403


def test_uploaded_original_is_persistent(browser):
    state, call = browser
    status, _, body = call("POST", "/api/browser/upload?name=page.png", raw=png(), cookie=False)
    assert status == 200, body
    page = json.loads(body)["pages"][0]
    status, _, original = call("GET", f"/api/pages/{page['id']}/image/original")
    assert status == 200
    assert original == png()
    record = state.store.open_project(state.project_id)["pages"][0]
    from pathlib import Path
    assert Path(record["source_path"]).is_relative_to(state.store.root / "imports")
    assert Path(record["source_path"]).is_file()


@pytest.mark.parametrize("name", ["../page.png", "..%2Fpage.png", "C:%5Cpage.png", "page.exe"])
def test_upload_rejects_unsafe_names(browser, name):
    _, call = browser
    assert call("POST", f"/api/browser/upload?name={name}", raw=png())[0] == 400


def test_upload_rejects_corrupt_image(browser):
    state, call = browser
    assert call("POST", "/api/browser/upload?name=bad.png", raw=b"not an image")[0] == 400
    assert not list((state.store.root / "imports").glob("*/*"))


def test_project_package_roundtrip(browser):
    _, call = browser
    assert call("POST", "/api/browser/upload?name=page.png", raw=png())[0] == 200
    status, _, body = call("POST", "/api/browser/project", {"editor": {}})
    assert status == 200, body
    url = json.loads(body)["download_url"]
    status, headers, archive = call("GET", url)
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    assert zipfile.is_zipfile(io.BytesIO(archive))
    assert call("POST", url, {})[0] == 405
    assert call("POST", "/api/project/close", {"force": True})[0] == 200
    assert call("GET", url)[0] == 404
    assert call("POST", "/api/browser/upload?name=saved.ilt.zip", raw=archive)[0] == 200


def test_default_server_remains_loopback(tmp_path):
    store = ProjectStore(tmp_path)
    state = AppState(AppSettings(), tmp_path / "settings.json", store, JobQueue(FakeWorker(store)))
    with pytest.raises(ValueError, match="127.0.0.1"):
        serve(state, host="0.0.0.0")


def test_duplicate_archive_names_keep_both_originals(browser):
    state, call = browser
    for color in ("red", "blue"):
        image = io.BytesIO()
        Image.new("RGB", (40, 40), color).save(image, format="PNG")
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("page.png", image.getvalue())
        assert call("POST", "/api/browser/upload?name=chapter.zip", raw=packed.getvalue())[0] == 200
    pages = state.store.open_project(state.project_id)["pages"]
    assert len(pages) == 2
    assert Image.open(pages[0]["source_path"]).getpixel((0, 0)) == (255, 0, 0)
    assert Image.open(pages[1]["source_path"]).getpixel((0, 0)) == (0, 0, 255)


def test_export_download_and_saved_status(browser):
    state, call = browser
    assert call("POST", "/api/browser/upload?name=page.png", raw=png())[0] == 200
    assert call("POST", "/api/jobs/translate", {"scope": "all"})[0] == 200
    status, _, body = call("POST", "/api/browser/export", {})
    assert status == 200, body
    result = json.loads(body)
    status, _, content = call("GET", result["download_url"])
    assert status == 200, content
    assert zipfile.is_zipfile(io.BytesIO(content))
    state.broadcast_pending()
    saved = json.loads((state.store.root / "exports" / (result["job_id"] + ".json")).read_text())
    assert saved["status"] == "done"
    from src.app.web_server import _download_export
    fresh = AppState(state.settings, state.settings_path, state.store, JobQueue(FakeWorker(state.store)))
    fresh.project_id = state.project_id
    assert _download_export(fresh, result["job_id"]).file.is_file()


def test_folder_upload_keeps_chapter(browser):
    state, call = browser
    assert call("POST", "/api/browser/upload?name=page.png&chapter=Book/Chapter%201", raw=png())[0] == 200
    assert state.store.open_project(state.project_id)["pages"][0]["chapter"] == "Book/Chapter 1"
