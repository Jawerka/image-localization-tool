"""Удалённый LAN API: сопряжение, лимиты, кэш и headless. Без моделей."""

from __future__ import annotations

import json
import socket
import threading
import time
from io import BytesIO

import pytest
from PIL import Image

from src.app.desktop import DesktopApp, parse_args, run_headless
from src.app.jobs import JobQueue
from src.app.remote import (
    MAX_BODY_BYTES,
    MAX_PIXELS,
    QueueFull,
    RemoteQueue,
    RemoteServer,
    _lan_ipv4,
    body_too_large,
    parse_multipart,
    pixel_too_large,
)
from src.app.remote_auth import hash_token, make_device
from src.app.remote_cache import CacheKey
from src.app.server import AppState
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker
from src.config import Config


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _request(port: int, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    from http.client import HTTPConnection

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        payload = response.read()
        header_map = {key.lower(): value for key, value in response.getheaders()}
        return response.status, header_map, payload
    finally:
        conn.close()


def _pair(port: int, code: str):
    return _request(
        port,
        "POST",
        "/v1/pair",
        body=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _auth_headers(token: str, extra: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def _translate(port: int, token: str, image: bytes, source: str = "en", target: str = "ru"):
    return _request(
        port,
        "POST",
        "/v1/translate",
        body=image,
        headers=_auth_headers(
            token,
            {
                "Content-Type": "image/png",
                "X-Source-Lang": source,
                "X-Target-Lang": target,
            },
        ),
    )


def _wait_job(port: int, token: str, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, _headers, body = _request(
            port,
            "GET",
            f"/v1/jobs/{job_id}",
            headers=_auth_headers(token),
        )
        assert status == 200
        last = json.loads(body)
        if last["status"] in ("done", "error"):
            return last
        time.sleep(0.02)
    raise AssertionError(last)


@pytest.fixture
def serve_remote(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.remote.remember_hash", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("src.app.remote_auth.forget_hash", lambda *_args, **_kwargs: None)
    started: list[RemoteServer] = []
    index = {"n": 0}

    def open_server(*, runner=None, clock=None, store=None, max_pending=8):
        index["n"] += 1
        server = RemoteServer(
            AppSettings(),
            cache_dir=tmp_path / f"cache-{index['n']}",
            store=store,
            runner=runner,
            clock=clock,
            max_pending=max_pending,
        )
        server.start("127.0.0.1", 0)
        started.append(server)
        return server

    yield open_server
    for server in started:
        server.shutdown()


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_status_snapshot_hides_token_hash(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.remote._lan_ipv4", lambda: ["10.0.0.8"])
    settings = AppSettings()
    settings.remote_devices = [
        {"id": "d1", "name": "phone", "token_hash": "deadbeef", "created": 3.5},
    ]
    server = RemoteServer(settings, cache_dir=tmp_path / "snap")
    assert server.status_snapshot()["pairing_code"] == ""
    code = server.pairing.issue_code()

    def forbid_issue():
        raise AssertionError("status_snapshot не должен выдавать новый код")

    server.pairing.issue_code = forbid_issue
    first = server.status_snapshot()
    second = server.status_snapshot()
    assert first == second
    assert set(first) == {
        "enabled",
        "port",
        "addresses",
        "pairing_code",
        "devices",
        "recent",
        "clients",
    }
    assert first["enabled"] is False
    assert first["port"] == 0
    assert first["addresses"] == ["10.0.0.8"]
    assert first["pairing_code"] == code
    assert first["devices"] == [{"id": "d1", "name": "phone", "created": 3.5}]
    assert first["clients"] == 1
    assert first["recent"] == []
    assert "token_hash" not in set(_walk_keys(first))
    assert "deadbeef" not in json.dumps(first)


def test_lan_ipv4_skips_loopback_until_last_resort(monkeypatch):
    def both(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
        ]

    class _Probe:
        def connect(self, _address):
            return None

        def getsockname(self):
            return ("127.0.0.1", 9)

        def close(self):
            return None

    monkeypatch.setattr("src.app.remote.socket.getaddrinfo", both)
    monkeypatch.setattr("src.app.remote.socket.socket", lambda *_args, **_kwargs: _Probe())
    assert _lan_ipv4() == ["10.1.2.3"]

    def only_loopback(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    def broken_socket(*_args, **_kwargs):
        raise OSError("нет сети")

    monkeypatch.setattr("src.app.remote.socket.getaddrinfo", only_loopback)
    monkeypatch.setattr("src.app.remote.socket.socket", broken_socket)
    assert _lan_ipv4() == ["127.0.0.1"]


def _wait_remote(job, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.status in ("done", "error"):
            return job
        time.sleep(0.02)
    return job


def test_remote_runner_uses_fake_worker(tmp_path):
    """Раннер ставит translate_page и закрывает задание PNG фейкового воркера."""
    store = ProjectStore(tmp_path / "store")
    worker = FakeWorker(store)
    settings = AppSettings(source_lang="ja", target_lang="de")
    state = AppState(
        settings=settings,
        settings_path=tmp_path / "settings.json",
        store=store,
        queue=JobQueue(worker),
        web_root=tmp_path / "web",
    )
    app = DesktopApp(state, None, None)
    server = RemoteServer(settings, cache_dir=tmp_path / "remote", store=store)
    app.remote_api = server
    state.remote_api = server
    app._bind_remote_runner(server)
    device = make_device("token-1", name="phone")
    job = server.submit_image(device, _png((10, 20, 30)), "en", "ru")
    finished = _wait_remote(job)
    assert finished.status == "done"
    assert finished.result
    assert finished.result.startswith(b"\x89PNG")
    assert len(worker.calls) == 1
    page_job = worker.calls[0]
    assert page_job.kind == "translate_page"
    assert page_job.project_id == job.project_id
    assert page_job.page_id == job.page_id
    assert page_job.payload["skip_ready"] is False
    assert page_job.payload["remote_job_id"] == job.id
    assert page_job.settings["source_lang"] == "en"
    assert page_job.settings["target_lang"] == "ru"
    assert state.remote_api is server

    bare = RemoteServer(AppSettings(), cache_dir=tmp_path / "bare", store=None)
    bare.set_runner(app._remote_runner)
    missing = bare.submit_image(make_device("token-2", name="other"), _png((1, 1, 1)), "en", "ru")
    failed = _wait_remote(missing)
    assert failed.status == "error"
    assert failed.error == "нет страницы Входящие"
    app._stop_remote()
    assert app.remote_api is None
    assert state.remote_api is None
    assert worker.on_page_done is None


def test_body_and_pixel_limits():
    assert body_too_large(MAX_BODY_BYTES) is False
    assert body_too_large(MAX_BODY_BYTES + 1) is True
    assert pixel_too_large(200_000, 200, MAX_PIXELS) is False
    assert pixel_too_large(200_000, 201, MAX_PIXELS) is True


def test_remote_settings_clamp_and_roundtrip():
    defaults = AppSettings()
    assert defaults.remote_enabled is False
    assert defaults.remote_bind == "0.0.0.0"
    assert defaults.remote_port == 8765
    assert defaults.remote_devices == []
    clamped = AppSettings(
        remote_bind="http://evil",
        remote_port=999999,
        remote_enabled="yes",
        translate_sfx=True,
        remote_devices=[
            {"id": "dev1", "name": "phone", "token_hash": "ab", "created": 1.5},
            {"id": "dev1", "name": "dup", "token_hash": "cd", "created": 2},
            "bad",
        ],
    )
    assert clamped.remote_bind == "0.0.0.0"
    assert clamped.remote_port == 65535
    assert clamped.remote_enabled is True
    assert clamped.translate_sfx is True
    assert clamped.remote_devices == [
        {"id": "dev1", "name": "phone", "token_hash": "ab", "created": 1.5}
    ]
    assert AppSettings(remote_port=0).remote_port == 1
    assert AppSettings(remote_bind="192.168.1.10").remote_bind == "192.168.1.10"
    restored = AppSettings.from_dict(clamped.to_dict())
    assert restored.remote_enabled is True
    assert restored.remote_port == 65535
    config = AppSettings(translate_sfx=True, remote_enabled=True, remote_port=9).to_config()
    assert config.translate_sfx is True
    assert isinstance(config, Config)
    assert not hasattr(config, "remote_enabled")


def test_headless_flags_and_idle(capsys):
    args = parse_args(["--headless", "--remote", r"D:\page.png"])
    assert args.headless is True
    assert args.remote is True
    assert args.browser is False
    assert args.paths == [r"D:\page.png"]
    assert parse_args([r"D:\page.png"]).headless is False
    code = run_headless(parse_args(["--headless"]))
    assert code == 0
    assert "Удалённый доступ выключен" in capsys.readouterr().out


def test_headless_remote_binds_runner(tmp_path, monkeypatch, capsys):
    from src.app import desktop as desktop_mod
    from src.app.paths import AppPaths, using_paths

    settings = AppSettings(remote_enabled=False, remote_bind="127.0.0.1", remote_port=0)
    settings.save(tmp_path / "settings.json")
    runners: list = []
    real_set = RemoteServer.set_runner

    def track_set(self, runner):
        runners.append(runner)
        return real_set(self, runner)

    monkeypatch.setattr(RemoteServer, "set_runner", track_set)
    monkeypatch.setattr(RemoteServer, "wait", lambda self: None)
    monkeypatch.setattr(desktop_mod, "HEADLESS_LOCAL_PORT", 0)
    monkeypatch.setattr("src.app.worker.ProcessWorker", FakeWorker)

    with using_paths(AppPaths(root=tmp_path, portable=True)):
        code = run_headless(parse_args(["--headless", "--remote"]))

    assert code == 0
    assert any(callable(item) for item in runners)
    token_file = tmp_path / "session.token"
    assert token_file.is_file()
    assert token_file.read_text(encoding="utf-8").strip()
    out = capsys.readouterr().out
    assert "Удалённый API слушает" in out
    assert "Локальный API" in out


def test_translate_requires_token(serve_remote):
    server = serve_remote(runner=lambda job: job.finish(_png((0, 255, 0))))
    status, _headers, body = _translate(server.port, "", _png((255, 0, 0)))
    assert status == 401
    assert json.loads(body)["error"]


def test_pair_token_translates_and_is_not_logged(serve_remote):
    result = _png((0, 255, 0))

    def runner(job):
        job.finish(result)

    server = serve_remote(runner=runner)
    code = server.pairing.issue_code()
    status, _headers, body = _pair(server.port, code)
    assert status == 200
    token = json.loads(body)["token"]
    assert token
    assert token not in json.dumps(server.settings.remote_devices)
    assert server.settings.remote_devices[-1]["token_hash"] == hash_token(token)
    posted, _headers, raw = _translate(server.port, token, _png((255, 0, 0)))
    assert posted == 202
    job_id = json.loads(raw)["job_id"]
    view = _wait_job(server.port, token, job_id)
    assert view == {
        "id": job_id,
        "status": "done",
        "stage": "done",
        "progress": 100,
        "position": 0,
        "error": "",
    }
    image_status, headers, image = _request(
        server.port,
        "GET",
        f"/v1/jobs/{job_id}/result",
        headers=_auth_headers(token),
    )
    assert image_status == 200
    assert headers["content-type"].startswith("image/png")
    assert image == result
    logged = json.dumps(server.recent_requests())
    assert token not in logged
    assert "PNG" not in logged


def test_expired_and_reused_codes(serve_remote):
    clock = {"now": 1000.0}
    server = serve_remote(clock=lambda: clock["now"])
    code = server.pairing.issue_code()
    assert _pair(server.port, code)[0] == 200
    assert _pair(server.port, code)[0] == 401
    fresh = server.pairing.issue_code()
    clock["now"] = 1000.0 + 301
    assert _pair(server.port, fresh)[0] == 401


def test_cors_preflight_echoes_extension_origin(serve_remote):
    server = serve_remote()
    status, headers, _body = _request(
        server.port,
        "OPTIONS",
        "/v1/translate",
        headers={
            "Origin": "chrome-extension://abc",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert status == 204
    assert headers["access-control-allow-origin"] == "chrome-extension://abc"
    assert headers["access-control-allow-methods"] == "GET, POST, DELETE"
    assert headers["access-control-allow-headers"] == (
        "Authorization, Content-Type, X-Source-Lang, X-Target-Lang"
    )
    moz, moz_headers, _body = _request(
        server.port,
        "OPTIONS",
        "/v1/health",
        headers={"Origin": "moz-extension://xyz"},
    )
    assert moz == 204
    assert moz_headers["access-control-allow-origin"] == "moz-extension://xyz"
    health, _headers, body = _request(server.port, "GET", "/v1/health")
    assert health == 200
    assert json.loads(body) == {"version": "dev", "ready": True}


def test_oversized_content_length_is_413(serve_remote):
    server = serve_remote(runner=lambda job: job.finish(_png((0, 255, 0))))
    code = server.pairing.issue_code()
    token = json.loads(_pair(server.port, code)[2])["token"]
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    sock.settimeout(3)
    try:
        message = (
            "POST /v1/translate HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{server.port}\r\n"
            f"Content-Length: {MAX_BODY_BYTES + 1}\r\n"
            "Content-Type: image/png\r\n"
            f"Authorization: Bearer {token}\r\n"
            "X-Source-Lang: en\r\n"
            "X-Target-Lang: ru\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.sendall(message.encode("ascii"))
        data = bytearray()
        while b"\r\n" not in data:
            piece = sock.recv(1024)
            if not piece:
                break
            data.extend(piece)
    finally:
        sock.close()
    assert b" 413 " in bytes(data).split(b"\r\n", 1)[0]


def test_small_image_and_multipart(serve_remote):
    seen: list[bytes] = []

    def runner(job):
        seen.append(job.image)
        job.finish(_png((0, 0, 255)))

    server = serve_remote(runner=runner)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    image = _png((255, 0, 0))
    status, _headers, body = _translate(server.port, token, image)
    assert status == 202
    _wait_job(server.port, token, json.loads(body)["job_id"])
    assert seen == [image]

    boundary = "----iltRemoteBoundary7f3a"
    other = _png((0, 255, 0))
    payload = b"".join(
        [
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="source_lang"\r\n\r\nen\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="target_lang"\r\n\r\nru\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            (
                b'Content-Disposition: form-data; name="file"; filename="a.png"\r\n'
                b"Content-Type: image/png\r\n\r\n"
            ),
            other,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    parsed = parse_multipart(payload, f"multipart/form-data; boundary={boundary}")
    assert parsed["file"] == other
    status, _headers, body = _request(
        server.port,
        "POST",
        "/v1/translate",
        body=payload,
        headers=_auth_headers(token, {"Content-Type": f"multipart/form-data; boundary={boundary}"}),
    )
    assert status == 202
    _wait_job(server.port, token, json.loads(body)["job_id"])
    assert seen[-1] == other


def test_cache_hit_does_not_call_runner_twice(serve_remote, tmp_path):
    calls: list[str] = []
    result = _png((0, 255, 0))

    def runner(job):
        calls.append(job.id)
        job.finish(result)

    store = ProjectStore(tmp_path / "projects")
    server = serve_remote(runner=runner, store=store)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    image = _png((255, 0, 0))
    first_status, _headers, first_body = _translate(server.port, token, image)
    assert first_status == 202
    first = _wait_job(server.port, token, json.loads(first_body)["job_id"])
    assert first["status"] == "done"
    assert calls and len(calls) == 1

    second_status, _headers, second_body = _translate(server.port, token, image)
    assert second_status == 202
    second_id = json.loads(second_body)["job_id"]
    second = _wait_job(server.port, token, second_id)
    assert second["status"] == "done"
    assert second["stage"] == "cache"
    assert len(calls) == 1
    image_status, _headers, image_body = _request(
        server.port,
        "GET",
        f"/v1/jobs/{second_id}/result",
        headers=_auth_headers(token),
    )
    assert image_status == 200
    assert image_body == result

    projects = store.list_projects()
    inbox = [item for item in projects if item.get("name") == "Входящие"]
    assert len(inbox) == 1
    assert inbox[0]["pages"]
    page_id = inbox[0]["pages"][-1]["id"]
    assert store.image_path(inbox[0]["id"], page_id, "result").is_file()
    assert store.page_status(inbox[0]["id"], page_id)["status"] == "done"


def test_fresh_skips_cache_and_replaces_it(serve_remote):
    calls: list[str] = []
    first_png = _png((0, 255, 0))
    second_png = _png((0, 0, 255))

    def runner(job):
        calls.append(job.id)
        job.finish(second_png if len(calls) > 1 else first_png)

    server = serve_remote(runner=runner)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    image = _png((255, 0, 0))
    status, _headers, body = _translate(server.port, token, image)
    assert status == 202
    done = _wait_job(server.port, token, json.loads(body)["job_id"])
    assert done["status"] == "done"
    assert len(calls) == 1

    status, _headers, body = _translate(server.port, token, image)
    cached = _wait_job(server.port, token, json.loads(body)["job_id"])
    assert cached["stage"] == "cache"
    assert len(calls) == 1

    boundary = "----iltFreshBoundary7f3a"
    payload = b"".join(
        [
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="source_lang"\r\n\r\nen\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="target_lang"\r\n\r\nru\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="fresh"\r\n\r\n1\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            (
                b'Content-Disposition: form-data; name="file"; filename="a.png"\r\n'
                b"Content-Type: image/png\r\n\r\n"
            ),
            image,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    status, _headers, body = _request(
        server.port,
        "POST",
        "/v1/translate",
        body=payload,
        headers=_auth_headers(token, {"Content-Type": f"multipart/form-data; boundary={boundary}"}),
    )
    assert status == 202
    fresh_id = json.loads(body)["job_id"]
    fresh = _wait_job(server.port, token, fresh_id)
    assert fresh["status"] == "done"
    assert fresh["stage"] != "cache"
    assert len(calls) == 2
    image_status, _headers, image_body = _request(
        server.port,
        "GET",
        f"/v1/jobs/{fresh_id}/result",
        headers=_auth_headers(token),
    )
    assert image_status == 200
    assert image_body == second_png

    status, _headers, body = _translate(server.port, token, image)
    replaced = _wait_job(server.port, token, json.loads(body)["job_id"])
    assert replaced["stage"] == "cache"
    assert len(calls) == 2
    image_status, _headers, image_body = _request(
        server.port,
        "GET",
        f"/v1/jobs/{json.loads(body)['job_id']}/result",
        headers=_auth_headers(token),
    )
    assert image_status == 200
    assert image_body == second_png


def test_revoked_token_is_401(serve_remote):
    server = serve_remote(runner=lambda job: job.finish(_png((0, 255, 0))))
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    device_id = server.settings.remote_devices[-1]["id"]
    server.revoke(device_id)
    status, _headers, _body = _translate(server.port, token, _png((255, 0, 0)))
    assert status == 401
    assert all(item["id"] != device_id for item in server.settings.remote_devices)


def test_unknown_job_delete_and_early_result(serve_remote):
    gate = threading.Event()

    def runner(job):
        gate.wait(3)
        job.finish(_png((0, 255, 0)))

    server = serve_remote(runner=runner)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    try:
        missing, _headers, _body = _request(
            server.port,
            "GET",
            "/v1/jobs/abcdef0123456789abcdef0123456789",
            headers=_auth_headers(token),
        )
        assert missing == 404
        posted, _headers, body = _translate(server.port, token, _png((255, 0, 0)))
        assert posted == 202
        job_id = json.loads(body)["job_id"]
        early, _headers, _body = _request(
            server.port,
            "GET",
            f"/v1/jobs/{job_id}/result",
            headers=_auth_headers(token),
        )
        assert early == 409
        deleted, _headers, payload = _request(
            server.port,
            "DELETE",
            f"/v1/jobs/{job_id}",
            headers=_auth_headers(token),
        )
        assert deleted == 204
        assert payload == b""
        gone, _headers, _body = _request(
            server.port,
            "GET",
            f"/v1/jobs/{job_id}",
            headers=_auth_headers(token),
        )
        assert gone == 404
    finally:
        gate.set()


def test_note_progress_appears_in_job_view(serve_remote):
    """Прогресс пайплайна виден в опросе. После done поздний вызов не откатывает статус."""
    gate = threading.Event()

    def runner(job):
        gate.wait(3)
        job.finish(_png((0, 255, 0)))

    server = serve_remote(runner=runner)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    try:
        posted, _headers, body = _translate(server.port, token, _png((255, 0, 0)))
        assert posted == 202
        job_id = json.loads(body)["job_id"]
        server.queue.note_progress(job_id, "ocr", 25)
        status, _headers, raw = _request(
            server.port,
            "GET",
            f"/v1/jobs/{job_id}",
            headers=_auth_headers(token),
        )
        assert status == 200
        view = json.loads(raw)
        assert view["status"] == "running"
        assert view["stage"] == "ocr"
        assert view["progress"] == 25
        gate.set()
        done = _wait_job(server.port, token, job_id)
        assert done["status"] == "done"
        assert done["progress"] == 100
        server.queue.note_progress(job_id, "detect", 8)
        after, _headers, after_body = _request(
            server.port,
            "GET",
            f"/v1/jobs/{job_id}",
            headers=_auth_headers(token),
        )
        assert after == 200
        frozen = json.loads(after_body)
        assert frozen["status"] == "done"
        assert frozen["progress"] == 100
        assert frozen["stage"] != "detect"
    finally:
        gate.set()


def test_status_poll_does_not_consume_rate_limit(serve_remote):
    """Опрос задания не съедает 30 запросов в минуту. Отправка картинки по-прежнему считается."""
    from src.app.remote_auth import RateLimiter

    server = serve_remote(runner=lambda job: job.finish(_png((1, 2, 3))))
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    server.limiter = RateLimiter(limit=2, window=60.0)
    missing = "/v1/jobs/abcdef0123456789abcdef0123456789"
    for _ in range(5):
        status, _headers, _body = _request(
            server.port,
            "GET",
            missing,
            headers=_auth_headers(token),
        )
        assert status == 404
    first, _headers, _body = _translate(server.port, token, _png((255, 0, 0)))
    second, _headers, _body = _translate(server.port, token, _png((0, 255, 0)))
    third, _headers, body = _translate(server.port, token, _png((0, 0, 255)))
    assert first == 202
    assert second == 202
    assert third == 429
    assert "Слишком много" in body.decode("utf-8")


def test_queue_full_returns_429(serve_remote):
    gate = threading.Event()

    def runner(job):
        gate.wait(3)
        job.finish(_png((0, 255, 0)))

    server = serve_remote(runner=runner, max_pending=1)
    token = json.loads(_pair(server.port, server.pairing.issue_code())[2])["token"]
    try:
        first, _headers, _body = _translate(server.port, token, _png((255, 0, 0)))
        assert first == 202
        second, _headers, _body = _translate(server.port, token, _png((0, 0, 255)))
        assert second == 429
    finally:
        gate.set()


def test_queue_full_without_http(tmp_path):
    queue = RemoteQueue(max_pending=1)
    key = CacheKey.build(b"a", "en", "ru", "fp")

    def make(raw: bytes):
        from src.app.remote import RemoteJob

        return RemoteJob(
            image=raw,
            source_lang="en",
            target_lang="ru",
            device_id="dev",
            cache_key=key,
        )

    queue.submit(make(b"a"))
    with pytest.raises(QueueFull):
        queue.submit(make(b"b"))
    server = RemoteServer(AppSettings(), cache_dir=tmp_path / "solo")
    assert server.queue.max_pending == 8
