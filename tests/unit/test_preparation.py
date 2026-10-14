"""Очередь подготовки сохраняет выбор и восстанавливается после остановки."""

import hashlib
import json
import time
import zipfile

import pytest

from src.app import component_catalog, downloads, preparation, runtime


@pytest.fixture
def fixture_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    components = []
    for name in ("detector", "lama", "rapidocr", "font", "font-pack"):
        path = tmp_path / (name + ".bin")
        path.write_bytes(name.encode())
        file = downloads.Artifact(path.name, (path.as_uri(),), downloads.digest(path), path.stat().st_size)
        components.append(component_catalog.Component(name, name, "model", (file,)))
    monkeypatch.setattr(component_catalog, "load", lambda *args: components)
    monkeypatch.setattr(component_catalog, "by_id", lambda id: next(c for c in components if c.id == id))
    wheel = tmp_path / "alpha.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("alpha.py", "VALUE=1")
    pack = runtime.Pack("torch-cpu", "CPU", "torch", "win", runtime.python_tag(), "1.0", "", "", wheel.stat().st_size,
                        files=(runtime.WheelFile(wheel.name, wheel.as_uri(), downloads.digest(wheel), wheel.stat().st_size),))
    monkeypatch.setattr(runtime, "platform_packs", lambda *args: [pack])
    monkeypatch.setattr(runtime, "pack_by_id", lambda id: pack)
    monkeypatch.setattr(runtime, "load_manifest", lambda *args: {"schema": 2, "packs": []})
    return {"source_lang": "en", "target_lang": "en", "device": "cpu"}


def wait(manager):
    deadline = time.monotonic() + 5
    while manager.busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not manager.busy()


def test_prepare_persists_ready_and_reuses_install(fixture_catalog, tmp_path):
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)
    assert manager.current()["state"] == "ready", manager.current()
    restored = preparation.Manager(path=tmp_path / "queue.json")
    assert restored.current()["state"] == "ready"
    assert preparation.plan(fixture_catalog)["total"] == 0


def test_interrupted_state_becomes_paused(fixture_catalog, tmp_path):
    state = preparation.plan(fixture_catalog)
    state["state"] = "installing"
    path = tmp_path / "queue.json"
    downloads.atomic_json(path, state)
    manager = preparation.Manager(path=path)
    assert manager.current()["state"] == "paused"
    manager.resume()
    wait(manager)
    assert manager.current()["state"] == "ready"


def test_resume_rejects_changed_catalog(fixture_catalog, tmp_path):
    state = preparation.plan(fixture_catalog)
    state["catalog_sha"] = "different"
    path = tmp_path / "queue.json"
    downloads.atomic_json(path, state)
    manager = preparation.Manager(path=path)
    with pytest.raises(ValueError, match="Каталог"):
        manager.resume()


def test_unsupported_offline_pair_is_explicit(fixture_catalog):
    with pytest.raises(ValueError, match="направление"):
        preparation.plan({**fixture_catalog, "target_lang": "xx", "translator_backend": "argos"})


def test_cannot_prepare_during_processing(fixture_catalog, tmp_path):
    manager = preparation.Manager(path=tmp_path / "queue.json", can_install=lambda: False)
    with pytest.raises(downloads.BusyError):
        manager.start(fixture_catalog)


def test_source_other_python_uses_installed_dependencies(fixture_catalog, monkeypatch):
    monkeypatch.setattr(runtime, "platform_packs", lambda *args: [])
    monkeypatch.setattr(preparation.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(preparation.importlib.metadata, "version", lambda name: "1.0")
    result = preparation.plan(fixture_catalog)
    assert result["items"][0]["type"] == "builtin"
    assert result["items"][0]["download_bytes"] == 0
