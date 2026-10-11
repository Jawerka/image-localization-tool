"""API компонентов рантайма: GET/download/remove и поле в bootstrap. Без HTTP-сокета."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import py7zr
import pytest

from src.app import runtime, server
from src.app.jobs import JobQueue
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker


@pytest.fixture(autouse=True)
def _clean_caches():
    runtime._manifest_cache.update({"data": None, "fetched": False, "started": False})
    runtime._ready_cache.update({"checked": False, "torch": False, "cuda": False})
    yield
    runtime._manifest_cache.update({"data": None, "fetched": False, "started": False})
    runtime._ready_cache.update({"checked": False, "torch": False, "cuda": False})


def _manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, packs: list[dict]) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1, "app": "1.0.0", "packs": packs}), encoding="utf-8")
    monkeypatch.setenv("ILT_RUNTIME_MANIFEST_URL", path.as_uri())
    monkeypatch.setenv("ILT_INSTALL_ROOT", str(tmp_path / "install"))
    monkeypatch.setattr(
        "src.app.hardware.detect",
        lambda refresh=False: {"recommended": "torch-cpu", "vendor": "none"},
    )


def _pack(pack_id: str = "argos", *, url: str = "", sha256: str = "") -> dict:
    return {
        "id": pack_id,
        "title": pack_id,
        "kind": "argos",
        "os": runtime.platform_tag(),
        "python": runtime.python_tag(),
        "version": "1.0",
        "url": url,
        "sha256": sha256,
        "size_bytes": 0,
    }


def _make_archive(path: Path) -> str:
    stage = path.parent / "stage"
    (stage / "site-packages" / "argostranslate").mkdir(parents=True)
    (stage / "site-packages" / "argostranslate" / "__init__.py").write_text("x=1", encoding="utf-8")
    with py7zr.SevenZipFile(path, "w") as archive:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(stage).as_posix())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(tmp_path: Path) -> server.AppState:
    store = ProjectStore(tmp_path / "store")
    return server.AppState(
        settings=AppSettings(),
        settings_path=tmp_path / "settings.json",
        store=store,
        queue=JobQueue(FakeWorker(store, synchronous=True)),
    )


def _wait_idle(state: server.AppState, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while state.runtime_manager().busy() and time.time() < deadline:
        time.sleep(0.01)


def test_runtime_status_lists_packs(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, [_pack("argos"), _pack("torch-cpu")])
    state = _state(tmp_path)
    result = server._api(state, "GET", "/api/runtime", {}, {})
    assert result.status == 200
    ids = [item["id"] for item in result.payload["packs"]]
    assert ids == ["argos", "torch-cpu"]
    assert result.payload["download"]["state"] == "idle"


def test_runtime_download_and_remove(monkeypatch, tmp_path):
    archive = tmp_path / "argos.7z"
    digest = _make_archive(archive)
    _manifest(monkeypatch, tmp_path, [_pack(url=archive.as_uri(), sha256=digest)])
    state = _state(tmp_path)
    box = state.subscribe()

    result = server._api(state, "POST", "/api/runtime/download", {"id": "argos"}, {})
    assert result.status == 202
    _wait_idle(state)
    assert runtime.is_installed("argos")

    received = []
    while not box.empty():
        received.append(box.get_nowait())
    states = [
        item["payload"]["state"]
        for item in received
        if item.get("type") == "runtime.progress"
    ]
    assert "downloading" in states
    assert states[-1] == "installed"

    result = server._api(state, "POST", "/api/runtime/remove", {"id": "argos"}, {})
    assert result.payload["ok"] is True
    assert not runtime.is_installed("argos")


def test_runtime_download_installed_is_noop(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, [_pack()])
    state = _state(tmp_path)
    directory = tmp_path / "install" / "runtime" / "argos"
    (directory / "site-packages").mkdir(parents=True)
    (directory / "pack.json").write_text(json.dumps({"id": "argos"}), encoding="utf-8")
    result = server._api(state, "POST", "/api/runtime/download", {"id": "argos"}, {})
    assert result.status == 200
    assert result.payload["installed"] is True


def test_runtime_download_unknown_pack(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, [_pack()])
    state = _state(tmp_path)
    with pytest.raises(server._HttpError) as excinfo:
        server._api(state, "POST", "/api/runtime/download", {"id": "nope"}, {})
    assert excinfo.value.status == 400


def test_runtime_remove_busy_pack_conflicts(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, [_pack()])
    state = _state(tmp_path)
    manager = state.runtime_manager()
    monkeypatch.setattr(manager, "busy", lambda: True)
    monkeypatch.setattr(manager, "current", lambda: {"id": "argos", "state": "downloading"})
    with pytest.raises(server._HttpError) as excinfo:
        server._api(state, "POST", "/api/runtime/remove", {"id": "argos"}, {})
    assert excinfo.value.status == 409


def test_bootstrap_includes_runtime_summary(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, [_pack()])
    monkeypatch.setattr(runtime, "torch_state", lambda refresh=False: (False, False))
    state = _state(tmp_path)
    payload = server._bootstrap(state)
    assert "runtime" in payload
    assert payload["runtime"]["recommended"] == "torch-cpu"
    assert payload["runtime"]["torch_ready"] is False
