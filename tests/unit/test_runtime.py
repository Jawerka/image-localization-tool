"""Компоненты рантайма: манифест, установка, активация. Без сети и настоящих паков."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import py7zr
import pytest

from src.app import runtime


@pytest.fixture(autouse=True)
def _clean_caches():
    runtime._manifest_cache.update({"data": None, "fetched": False, "started": False})
    runtime._ready_cache.update({"checked": False, "torch": False, "cuda": False})
    yield
    runtime._manifest_cache.update({"data": None, "fetched": False, "started": False})
    runtime._ready_cache.update({"checked": False, "torch": False, "cuda": False})


def _pack_dict(pack_id: str = "torch-cpu", kind: str = "torch", *, url: str = "", sha256: str = "",
               size: int = 0, platform: str | None = None, python: str | None = None,
               driver_min: int | None = None) -> dict:
    entry = {
        "id": pack_id,
        "title": pack_id,
        "kind": kind,
        "os": platform or runtime.platform_tag(),
        "python": python or runtime.python_tag(),
        "version": "1.0",
        "url": url,
        "sha256": sha256,
        "size_bytes": size,
    }
    if driver_min is not None:
        entry["driver_min"] = driver_min
    return entry


def _use(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, packs: list[dict]) -> Path:
    """Манифест через env-URL и отдельный install_root для теста."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1, "app": "1.0.0", "packs": packs}), encoding="utf-8")
    monkeypatch.setenv("ILT_RUNTIME_MANIFEST_URL", path.as_uri())
    monkeypatch.setenv("ILT_INSTALL_ROOT", str(tmp_path / "install"))
    return path


def _make_pack_archive(path: Path, marker: str = "torch") -> str:
    """Собрать .7z с ``site-packages/<marker>/__init__.py``. Возвращает sha256."""
    stage = path.parent / (path.stem + "-stage")
    package = stage / "site-packages" / marker
    (package / "lib").mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "lib" / "native.dll").write_bytes(b"MZ")
    _write_archive(path, stage)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_archive(path: Path, stage: Path) -> None:
    """py7zr.writeall пишет абсолютный префикс — кладём файлы явными путями."""
    with py7zr.SevenZipFile(path, "w") as archive:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(stage).as_posix())


def _install_marker(root: Path, pack_id: str, *, site: bool = True) -> Path:
    directory = root / "runtime" / pack_id
    (directory / "site-packages").mkdir(parents=True, exist_ok=site)
    (directory / "pack.json").write_text(
        json.dumps({"id": pack_id, "version": "1.0", "sha256": "", "installed_at": 0.0}),
        encoding="utf-8",
    )
    return directory


def test_platform_packs_filters_os_and_python(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [
        _pack_dict("torch-cpu", platform="win", python="310"),
        _pack_dict("torch-cpu", platform="linux", python="310"),
        _pack_dict("argos", kind="argos", platform="win", python="39"),
    ])
    monkeypatch.setattr(runtime, "platform_tag", lambda: "win")
    monkeypatch.setattr(runtime, "python_tag", lambda: "310")
    ids = [pack.id for pack in runtime.platform_packs()]
    assert ids == ["torch-cpu"]


def test_pack_by_id_unknown_raises(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("torch-cpu")])
    with pytest.raises(KeyError):
        runtime.pack_by_id("nope")


def test_pack_by_id_rejects_bad_charset(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("torch-cpu")])
    with pytest.raises(ValueError):
        runtime.pack_by_id("../evil")


def test_status_reports_installed(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [
        _pack_dict("torch-cpu"),
        _pack_dict("torch-cu128", driver_min=570),
    ])
    _install_marker(tmp_path / "install", "torch-cpu")
    monkeypatch.setattr(
        "src.app.hardware.detect",
        lambda refresh=False: {"recommended": "torch-cu128", "vendor": "nvidia"},
    )
    monkeypatch.setattr(runtime, "torch_state", lambda refresh=False: (False, False))
    payload = runtime.status("auto")
    by_id = {item["id"]: item for item in payload["packs"]}
    assert by_id["torch-cpu"]["state"] == "installed"
    assert by_id["torch-cpu"]["installed_version"] == "1.0"
    assert by_id["torch-cu128"]["state"] == "available"
    assert by_id["torch-cu128"]["recommended"] is True
    assert payload["download"]["state"] == "idle"


def test_download_install_and_remove(monkeypatch, tmp_path):
    archive = tmp_path / "argos.7z"
    digest = _make_pack_archive(archive, marker="argostranslate")
    _use(monkeypatch, tmp_path, [
        _pack_dict("argos", kind="argos", url=archive.as_uri(), sha256=digest, size=archive.stat().st_size),
    ])
    events: list[tuple] = []
    destination = runtime.download_and_install(
        "argos", lambda done, total, state, message: events.append((state, done, message))
    )
    assert (destination / "site-packages" / "argostranslate" / "__init__.py").is_file()
    assert runtime.is_installed("argos")
    assert runtime.installed_ids() == ["argos"]
    assert events[0][0] == "downloading"
    assert events[-1][0] == "installed"
    assert not list((tmp_path / "install" / "runtime").glob("*.part"))
    assert runtime.remove("argos") is True
    assert runtime.remove("argos") is False
    assert not runtime.is_installed("argos")


def test_sha_mismatch_leaves_no_trace(monkeypatch, tmp_path):
    archive = tmp_path / "torch-cpu.7z"
    _make_pack_archive(archive)
    _use(monkeypatch, tmp_path, [
        _pack_dict("torch-cpu", url=archive.as_uri(), sha256="0" * 64),
    ])
    with pytest.raises(RuntimeError, match="sha256"):
        runtime.download_and_install("torch-cpu")
    root = tmp_path / "install" / "runtime"
    assert not runtime.is_installed("torch-cpu")
    assert not (root / "torch-cpu.part").exists()
    assert not (root / "torch-cpu.tmp").exists()


def test_archive_without_site_packages_is_rejected(monkeypatch, tmp_path):
    stage = tmp_path / "stage"
    (stage / "other").mkdir(parents=True)
    (stage / "other" / "file.txt").write_text("x", encoding="utf-8")
    archive = tmp_path / "bad.7z"
    _write_archive(archive, stage)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    _use(monkeypatch, tmp_path, [
        _pack_dict("argos", kind="argos", url=archive.as_uri(), sha256=digest),
    ])
    with pytest.raises(RuntimeError, match="site-packages"):
        runtime.download_and_install("argos")


def test_traversal_names_are_rejected(monkeypatch, tmp_path):
    class FakeArchive:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getnames(self):
            return ["../evil.py"]

        def extractall(self, path=None):
            raise AssertionError("extractall не должен вызываться")

    fake_module = types.ModuleType("py7zr")
    fake_module.SevenZipFile = FakeArchive
    monkeypatch.setitem(sys.modules, "py7zr", fake_module)
    pack = runtime.Pack("argos", "argos", "argos", "win", "310", "1.0", "", "", 0)
    with pytest.raises(RuntimeError, match="Недопустимый путь"):
        runtime._extract_pack(pack, tmp_path / "a.7z", tmp_path / "tmp")


def test_activate_prefers_cu128(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("torch-cpu"), _pack_dict("torch-cu128")])
    install = tmp_path / "install"
    _install_marker(install, "torch-cpu")
    _install_marker(install, "torch-cu128")
    before = list(sys.path)
    try:
        activated = runtime.activate()
        assert activated == ["torch-cpu", "torch-cu128"]
        cu128 = str(install / "runtime" / "torch-cu128" / "site-packages")
        cpu = str(install / "runtime" / "torch-cpu" / "site-packages")
        assert sys.path.index(cu128) < sys.path.index(cpu)
    finally:
        sys.path[:] = before


def test_activate_skips_directories_without_marker(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("torch-cpu")])
    install = tmp_path / "install"
    (install / "runtime" / "torch-cpu" / "site-packages").mkdir(parents=True)
    before = list(sys.path)
    try:
        assert runtime.activate() == []
    finally:
        sys.path[:] = before


def test_manager_emits_runtime_progress(monkeypatch, tmp_path):
    archive = tmp_path / "argos.7z"
    digest = _make_pack_archive(archive, marker="argostranslate")
    _use(monkeypatch, tmp_path, [
        _pack_dict("argos", kind="argos", url=archive.as_uri(), sha256=digest),
    ])
    events: list = []

    class _Event:
        def __init__(self, type_, payload):
            self.type = type_
            self.payload = payload

    monkeypatch.setattr(runtime, "WorkerEvent", _Event)
    manager = runtime.Manager(fanout=events.append)
    manager.start("argos")
    deadline = 30.0
    import time
    while manager.busy() and deadline > 0:
        time.sleep(0.01)
        deadline -= 0.01
    assert manager.current()["state"] == "installed"
    assert events and events[-1].type == "runtime.progress"
    assert events[-1].payload["state"] == "installed"


def test_torch_state_is_false_without_pack(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("torch-cpu")])
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert runtime.torch_state(refresh=True) == (False, False)
    assert "torch" not in sys.modules
    assert runtime.effective_device("auto") == "cpu"
    assert runtime.effective_device("cuda") == "cuda"


def test_summary_reports_installed(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, [_pack_dict("argos", kind="argos")])
    _install_marker(tmp_path / "install", "argos")
    monkeypatch.setattr(
        "src.app.hardware.detect",
        lambda refresh=False: {"recommended": "torch-cpu"},
    )
    monkeypatch.setattr(runtime, "torch_state", lambda refresh=False: (False, False))
    summary = runtime.summary("auto")
    assert summary["installed"] == ["argos"]
    assert summary["recommended"] == "torch-cpu"
    assert summary["torch_ready"] is False
    assert summary["argos_ready"] is True


def test_manifest_fetched_when_bundled_has_no_real_platform_sha(monkeypatch, tmp_path):
    """Linux-база с плейсхолдерами (пустой sha) тянет релизный манифест синхронно."""
    monkeypatch.delenv(runtime.MANIFEST_ENV, raising=False)
    monkeypatch.setenv("ILT_INSTALL_ROOT", str(tmp_path / "install"))
    placeholder = _pack_dict("torch-cpu")
    placeholder["sha256"] = ""
    fetched = {"schema": 1, "app": "1.0.0", "packs": [_pack_dict("torch-cpu")]}
    monkeypatch.setattr(runtime, "_fetch_manifest", lambda url: fetched)
    monkeypatch.setattr(
        runtime,
        "_read_manifest_file",
        lambda path: {"schema": 1, "app": "1.0.0", "packs": [placeholder]},
    )
    monkeypatch.setattr(
        runtime, "bundled_manifest_path", lambda: tmp_path / "bundled.json"
    )
    data = runtime.load_manifest(force=True)
    assert data["packs"] and data["packs"][0]["sha256"] == fetched["packs"][0]["sha256"]


def test_manifest_not_fetched_when_bundled_sha_present(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime.MANIFEST_ENV, raising=False)
    monkeypatch.setenv("ILT_INSTALL_ROOT", str(tmp_path / "install"))
    bundled_pack = _pack_dict("torch-cpu")
    bundled_pack["sha256"] = "a" * 64
    calls: list[str] = []
    monkeypatch.setattr(runtime, "_fetch_manifest", lambda url: calls.append(url) or None)
    monkeypatch.setattr(
        runtime,
        "_read_manifest_file",
        lambda path: {"schema": 1, "app": "1.0.0", "packs": [bundled_pack]},
    )
    monkeypatch.setattr(
        runtime, "bundled_manifest_path", lambda: tmp_path / "bundled.json"
    )
    monkeypatch.setattr(runtime, "_start_background_refresh", lambda: None)
    data = runtime.load_manifest(force=True)
    assert data["packs"][0]["id"] == "torch-cpu"
    assert calls == []
