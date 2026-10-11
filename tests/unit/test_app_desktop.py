"""Окно и один экземпляр без pywebview, ProcessWorker и внешнего сетевого доступа."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from src.app.desktop import (
    TITLE,
    InstanceEndpoint,
    WebViewBridge,
    _parent_alive,
    _write_api_ready,
    closing_allowed,
    decide_role,
    focus_window,
    forward_to_running,
    hwnd_from_native,
    instance_path,
    parse_args,
    pid_alive,
    read_instance,
    run_api,
    run_webview,
    window_kwargs,
    write_instance,
)
from src.app.paths import AppPaths, using_paths
from src.app.settings import AppSettings


def _unused_pid() -> int:
    for candidate in (999_999_937, 999_999_893, 1_999_999_993, 2_000_000_003):
        if not pid_alive(candidate):
            return candidate
    raise AssertionError("не нашёлся свободный pid")


def _close_log_stream(stream) -> None:
    if getattr(stream, "ilt_log_stream", False):
        stream.close()


def test_second_client_delivers_paths(tmp_path):
    assert pid_alive(os.getpid())
    received: list[list[str]] = []
    ready = threading.Event()

    def on_paths(paths: list[str]) -> None:
        received.append(list(paths))
        ready.set()

    endpoint = InstanceEndpoint(tmp_path, on_paths)
    endpoint.start()
    try:
        sent = [r"D:\Манга\a.png", r"D:\Манга"]
        assert forward_to_running(tmp_path, sent) is True
        assert ready.wait(2)
        assert received == [sent]
    finally:
        endpoint.close()
    assert not instance_path(tmp_path).exists()


def test_dead_pid_does_not_block_first(tmp_path):
    dead = _unused_pid()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    probe.listen(1)
    probe.settimeout(0.3)
    port = int(probe.getsockname()[1])
    write_instance(instance_path(tmp_path), dead, port)
    record = read_instance(instance_path(tmp_path))
    assert record is not None
    assert decide_role(record, alive=False, connected=False) == "first"
    endpoint = None
    try:
        assert forward_to_running(tmp_path, ["page.png"]) is False
        with pytest.raises(TimeoutError):
            probe.accept()
        endpoint = InstanceEndpoint(tmp_path, lambda _paths: None)
        endpoint.start()
        info = read_instance(instance_path(tmp_path))
        assert info is not None
        assert info.pid == os.getpid()
        assert info.port != port
    finally:
        probe.close()
        if endpoint is not None:
            endpoint.close()
    assert not instance_path(tmp_path).exists()


def test_failed_connection_becomes_first(tmp_path):
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    port = int(held.getsockname()[1])
    write_instance(instance_path(tmp_path), os.getpid(), port)
    endpoint = None
    try:
        assert pid_alive(os.getpid())
        assert forward_to_running(tmp_path, ["a.png"]) is False
        record = read_instance(instance_path(tmp_path))
        assert decide_role(record, alive=True, connected=False) == "first"
        endpoint = InstanceEndpoint(tmp_path, lambda _paths: None)
        endpoint.start()
        info = read_instance(instance_path(tmp_path))
        assert info is not None
        assert info.pid == os.getpid()
        assert info.port != port
    finally:
        held.close()
        if endpoint is not None:
            endpoint.close()


def test_closing_when_busy_needs_confirmation():
    assert closing_allowed(True, False) is False
    assert closing_allowed(False, False) is True
    assert closing_allowed(True, True) is True


def test_parse_args_browser_and_paths():
    browser = parse_args(["--browser", r"D:\a.png", r"D:\folder"])
    assert browser.browser is True
    assert browser.paths == [r"D:\a.png", r"D:\folder"]
    plain = parse_args([r"D:\page.png"])
    assert plain.browser is False
    assert plain.paths == [r"D:\page.png"]
    mixed = parse_args([r"D:\folder", "--browser", "b.jpg"])
    assert mixed.browser is True
    assert mixed.paths == [r"D:\folder", "b.jpg"]


def test_parse_args_api_and_parent_pid():
    api = parse_args(["--api", "--parent-pid", "4321"])
    assert api.api is True
    assert api.parent_pid == 4321
    assert api.paths == []
    assert api.headless is False
    plain = parse_args([r"D:\page.png"])
    assert plain.api is False
    assert plain.parent_pid is None


def test_parent_alive_detects_process():
    assert _parent_alive(os.getpid()) is True
    assert _parent_alive(_unused_pid()) is False
    assert _parent_alive(0) is False
    assert _parent_alive(-1) is False


def test_write_api_ready_payload(tmp_path):
    with using_paths(AppPaths(root=tmp_path, portable=True)):
        path = _write_api_ready(4321, "tok-123")
        assert path == tmp_path / "api.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == {"port": 4321, "token": "tok-123"}


def _api_get(port: int, token: str | None) -> tuple[int, dict]:
    headers = {"Cookie": f"ilt_session={token}"} if token else {}
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/api/bootstrap", headers=headers)
        response = conn.getresponse()
        body = response.read()
        return response.status, json.loads(body.decode("utf-8"))
    finally:
        conn.close()


def test_launch_dispatches_api(monkeypatch):
    import src.app.desktop as desktop

    called: list = []

    def fake_run_api(args):
        called.append(args)
        return 7

    monkeypatch.setattr(desktop, "run_api", fake_run_api)
    assert desktop.launch(["--api", "--parent-pid", "5"]) == 7
    assert called and called[0].api is True
    assert called[0].parent_pid == 5


def test_run_api_handshake_cookie_and_parent_watch(tmp_path, monkeypatch):
    import src.app.desktop as desktop

    monkeypatch.setattr(desktop, "data_root", lambda: tmp_path)
    monkeypatch.setattr(desktop, "settings_path", lambda: tmp_path / "settings.json")
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    done = threading.Event()
    args = parse_args(["--api", "--parent-pid", str(parent.pid)])

    def runner() -> None:
        try:
            run_api(args)
        finally:
            done.set()

    thread = threading.Thread(target=runner, name="ilt-api-test", daemon=True)
    thread.start()
    try:
        ready = tmp_path / "api.json"
        info: dict | None = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                info = json.loads(ready.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = None
            if info:
                break
            time.sleep(0.05)
        assert info, "api.json не появился"
        assert int(info.get("port") or 0) > 0
        token = str(info.get("token") or "")
        assert token
        assert not (tmp_path / "instance.json").exists()

        status, payload = _api_get(int(info["port"]), token)
        assert status == 200
        assert payload.get("settings") is not None
        denied, _ = _api_get(int(info["port"]), None)
        assert denied == 401
        wrong, _ = _api_get(int(info["port"]), "not-the-token")
        assert wrong == 401

        parent.kill()
        assert done.wait(15), "sidecar не завершился после смерти родителя"
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)
    assert not ready.exists()


def test_run_api_starts_remote_when_enabled_in_settings(tmp_path, monkeypatch):
    """run_api — зеркало оконного режима: remote_enabled в настройках поднимает LAN."""
    import src.app.desktop as desktop
    import src.app.remote as remote_mod

    calls: list = []

    class StubRemote:
        def __init__(self, settings, settings_path=None, store=None):
            calls.append("init")

        def start(self, bind, port):
            calls.append(f"start:{bind}:{port}")
            return 43210

        def set_runner(self, runner):
            calls.append("runner")

        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr(remote_mod, "RemoteServer", StubRemote)
    monkeypatch.setattr(desktop, "data_root", lambda: tmp_path)
    monkeypatch.setattr(desktop, "settings_path", lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema": 1, "remote_enabled": True}),
        encoding="utf-8",
    )
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    args = parse_args(["--api", "--parent-pid", str(parent.pid)])
    done = threading.Event()

    def runner() -> None:
        try:
            run_api(args)
        finally:
            done.set()

    thread = threading.Thread(target=runner, name="ilt-api-remote-test", daemon=True)
    thread.start()
    try:
        ready = tmp_path / "api.json"
        deadline = time.time() + 20
        while time.time() < deadline and not ready.exists():
            time.sleep(0.05)
        assert ready.exists(), "api.json не появился"
        assert "init" in calls, "LAN-слушатель не поднялся при remote_enabled"
        assert any(str(item).startswith("start:") for item in calls)
    finally:
        parent.kill()
        assert done.wait(15), "sidecar не остановился"
    assert "shutdown" in calls


def test_null_stdout_import_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    sys.modules.pop("src.app.__main__", None)
    try:
        with using_paths(AppPaths(root=tmp_path, portable=True)):
            import src.app.__main__ as entry

            assert entry.sys.stdout is not None
            assert entry.sys.stderr is not None
            assert entry.sys.stdout is entry.sys.stderr
            entry.sys.stdout.write("строка-из-потока\n")
            entry.sys.stdout.flush()
            text = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
        assert "строка-из-потока" in text
    finally:
        _close_log_stream(sys.stdout)
        _close_log_stream(sys.stderr)


def test_missing_webview2_shows_message(monkeypatch):
    calls = []

    def box(hwnd, text, title, flags):
        calls.append((hwnd, text, title, flags))
        return 0

    monkeypatch.setattr(desktop_user32(), "MessageBoxW", box)

    def boom() -> None:
        raise RuntimeError("нет WebView2")

    assert run_webview(boom) == 1
    assert calls
    text, title = calls[0][1], calls[0][2]
    assert "WebView2" in text
    assert title == TITLE


def test_webview_bridge_quit_destroys_window():
    destroyed: list[bool] = []

    class StubApp:
        def __init__(self):
            self.window = SimpleNamespace(destroy=lambda: destroyed.append(True))
            self._skip_busy_close_confirm = False

    app = StubApp()
    bridge = WebViewBridge(app)  # type: ignore[arg-type]
    bridge.quit(True)
    assert destroyed == [True]
    assert app._skip_busy_close_confirm is True

    app2 = StubApp()
    bridge2 = WebViewBridge(app2)  # type: ignore[arg-type]
    bridge2.destroy()
    assert app2._skip_busy_close_confirm is False


def test_window_kwargs_from_settings():
    defaults = window_kwargs(AppSettings())
    assert defaults["width"] == 1280
    assert defaults["height"] == 800
    assert defaults["min_size"] == (1100, 700)
    assert defaults["zoomable"] is False
    assert "x" not in defaults
    assert "y" not in defaults
    placed = window_kwargs(AppSettings(window_x=12, window_y=34, window_width=1400, window_height=900))
    assert placed["x"] == 12
    assert placed["y"] == 34
    assert placed["width"] == 1400
    assert placed["height"] == 900


def test_post_drop_uses_session_cookie(tmp_path):
    from PIL import Image

    from src.app.desktop import post_drop
    from src.app.dialogs import DialogBridge
    from src.app.jobs import JobQueue
    from src.app.server import AppState, serve
    from src.app.store import ProjectStore
    from src.app.worker import FakeWorker

    page = tmp_path / "page.png"
    Image.new("RGB", (8, 8), "white").save(page)
    state = AppState(
        settings=AppSettings(),
        settings_path=tmp_path / "settings.json",
        store=ProjectStore(tmp_path / "store"),
        queue=JobQueue(FakeWorker()),
        dialogs=DialogBridge(),
        web_root=tmp_path / "web",
        token="session-token",
    )
    httpd, port = serve(state)
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="ilt-http-test",
        daemon=True,
    )
    thread.start()
    try:
        status = post_drop(port, state.token, [str(page)])
        assert status == 200
        assert state.project_id
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_webview2_version_string():
    from src.app.desktop import _webview2_version_ok

    assert _webview2_version_ok("151.0.4129.107")
    assert not _webview2_version_ok("0.0.0.0")
    assert not _webview2_version_ok("0")
    assert not _webview2_version_ok("")


def test_focus_without_handle_does_not_raise(monkeypatch):
    calls = []

    def fake_foreground(hwnd):
        calls.append(int(hwnd))
        return 1

    monkeypatch.setattr(desktop_user32(), "SetForegroundWindow", fake_foreground)
    focus_window(None)
    focus_window(object())
    assert calls == []
    assert hwnd_from_native(None) is None
    assert hwnd_from_native(0) is None

    class _Handle:
        def ToInt64(self) -> int:
            return 77

    class _Form:
        Handle = _Handle()

    assert hwnd_from_native(_Form()) == 77
    focus_window(SimpleNamespace(native=123, minimized=False))
    assert calls == [123]


def desktop_user32():
    import src.app.desktop as desktop

    return desktop.ctypes.windll.user32
