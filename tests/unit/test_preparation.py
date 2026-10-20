"""Очередь подготовки сохраняет выбор и восстанавливается после остановки."""

import hashlib
import threading
import time
import zipfile

import pytest

from src.app import component_catalog, downloads, preparation, runtime
from src.config import Config


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


def test_plan_and_gate_do_not_hash_installed_files(fixture_catalog, tmp_path, monkeypatch):
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)
    monkeypatch.setattr(downloads, "digest", lambda *_: (_ for _ in ()).throw(AssertionError("hash")))
    assert preparation.plan(fixture_catalog)["total"] == 0
    assert preparation.missing(fixture_catalog) == []


def test_revalidation_does_not_prefetch_installed_files(fixture_catalog, tmp_path):
    """Смена проверяющей сборки не требует архивов уже установленных файлов."""
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)
    assert manager.current()["state"] == "ready"
    items = preparation.plan(fixture_catalog)["items"]
    for item in items:
        item["ready"] = False
        assert item["install_bytes"] == 0
    assert preparation._planned_artifacts(items) == []


def test_all_files_prefetch_before_serial_install(fixture_catalog, tmp_path, monkeypatch):
    events = []
    real_fetch = downloads.fetch

    def record_fetch(item, *args, **kwargs):
        events.append(("download", item.name))
        return real_fetch(item, *args, **kwargs)

    def record_runtime(_pack, progress, pause=None):
        events.append(("install", "runtime"))

    def record_component(component, progress, pause, models_dir):
        events.append(("install", component.id))

    monkeypatch.setattr(downloads, "fetch", record_fetch)
    monkeypatch.setattr(runtime, "download_and_install", record_runtime)
    monkeypatch.setattr(component_catalog, "install", record_component)
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)

    assert manager.current()["state"] == "ready", manager.current()
    first_install = next(index for index, event in enumerate(events) if event[0] == "install")
    assert all(event[0] == "download" for event in events[:first_install])
    assert all(event[0] == "install" for event in events[first_install:])
    assert len([event for event in events if event[0] == "install"]) == 6


def test_verify_repairs_corrupted_installed_component(fixture_catalog, tmp_path):
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)
    component = component_catalog.by_id("lama")
    folder = component_catalog.directory(component)
    (folder / component.files[0].name).write_bytes(b"broken")
    manager.start(fixture_catalog, verify=True)
    wait(manager)
    assert manager.current()["state"] == "ready", manager.current()
    assert (folder / component.files[0].name).read_bytes() == b"lama"
    assert manager.current().get("verified_at")


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


def test_resume_recalculates_remaining_disk_space(fixture_catalog, tmp_path, monkeypatch):
    manager = preparation.Manager(path=tmp_path / "queue.json")
    manager.start(fixture_catalog)
    wait(manager)
    assert manager.current()["state"] == "ready"
    saved = manager.current()
    saved.update(state="paused", required_space=10**12)
    downloads.atomic_json(manager.path, saved)
    restored = preparation.Manager(path=manager.path)
    calls = []
    monkeypatch.setattr(downloads, "ensure_space", lambda path, required, *args: calls.append(required))
    restored.resume()
    wait(restored)
    assert restored.current()["state"] == "ready"
    assert calls[0] == 0


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


def test_explicit_gpu_alias_is_normalized(fixture_catalog):
    result = preparation.plan({**fixture_catalog, "device": "gpu"})
    assert result["selection"]["device"] == "cuda"


def test_legacy_components_are_copied_into_program_folder(tmp_path):
    target = tmp_path / "app"
    target.mkdir()
    legacy = tmp_path / "legacy"
    (legacy / ".resources" / "detector").mkdir(parents=True)
    (legacy / ".resources" / "detector" / "model.onnx").write_bytes(b"model")
    (target / "runtime").mkdir()
    (target / "runtime" / "keep.txt").write_text("keep", encoding="utf-8")

    migrated = preparation.migrate_legacy_components(target, legacy)

    assert migrated == [".resources"]
    assert (target / ".resources" / "detector" / "model.onnx").read_bytes() == b"model"
    assert (target / "runtime" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (legacy / ".resources" / "detector" / "model.onnx").is_file()


def test_auto_source_resolves_default_offline_pair(fixture_catalog, tmp_path, monkeypatch):
    path = tmp_path / "language.zip"
    path.write_bytes(b"zip")
    file = downloads.Artifact(path.name, (path.as_uri(),), downloads.digest(path), path.stat().st_size)
    language = component_catalog.Component("language-en-ru", "en → ru", "language", (file,), source="en", target="ru")
    components = [*component_catalog.load(), language]
    monkeypatch.setattr(component_catalog, "load", lambda *args: components)
    monkeypatch.setattr(component_catalog, "by_id", lambda id: next(c for c in components if c.id == id))
    result = preparation.plan({**fixture_catalog, "source_lang": "auto", "target_lang": "ru",
                               "translator_backend": "argos"})
    assert any(item["id"] == "language-en-ru" for item in result["items"])


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


def test_prefetch_worker_limit_and_sha_deduplication(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    artifacts = []
    for index in range(8):
        path = tmp_path / f"asset-{index}.bin"
        path.write_bytes(f"asset-{index}".encode())
        artifacts.append(downloads.Artifact(path.name, (path.as_uri(),), downloads.digest(path), path.stat().st_size))

    lock = threading.Lock()
    active = 0
    maximum = 0
    calls = []
    real_fetch = downloads.fetch

    def tracked_fetch(item, *args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            calls.append(item.sha256)
        try:
            time.sleep(0.04)
            return real_fetch(item, *args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(downloads, "fetch", tracked_fetch)
    repeated = downloads.Artifact("same-content.bin", artifacts[0].urls, artifacts[0].sha256,
                                  artifacts[0].size_bytes)
    assert preparation._prefetch_workers(99) == 4
    assert preparation._prefetch_workers(0) == 1
    assert preparation._prefetch_workers("bad") == 3
    assert Config().download_prefetch_workers == 3
    assert len(preparation._unique_artifacts([*artifacts, repeated])) == len(artifacts)

    transferred = []
    total = preparation._prefetch_missing([*artifacts, repeated], 3, threading.Event(),
                                          lambda done, size: transferred.append((done, size)))

    assert total == sum(item.size_bytes for item in artifacts)
    assert len(calls) == len(artifacts)
    assert 2 <= maximum <= 3
    assert transferred[-1] == (total, total)
    assert [value[0] for value in transferred] == sorted(value[0] for value in transferred)


def test_unique_artifacts_reject_conflicting_size():
    digest = hashlib.sha256(b"x").hexdigest()
    items = [downloads.Artifact("one", ("https://example.test/one",), digest, 1),
             downloads.Artifact("two", ("https://example.test/two",), digest, 2)]
    with pytest.raises(ValueError, match="разными размерами"):
        preparation._unique_artifacts(items)
