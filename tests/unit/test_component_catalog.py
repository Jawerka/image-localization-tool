"""Проверка целостности и транзакций внешних ресурсов."""

import json

import pytest

from src.app import component_catalog as catalog, downloads


def component(tmp_path, payload=b"model", check=""):
    path = tmp_path / "weights.bin"
    path.write_bytes(payload)
    return catalog.Component("demo", "demo", "model", (downloads.Artifact(path.name, (path.as_uri(),),
        downloads.digest(path), len(payload)),), check)


def test_component_probe_temp_dir_is_in_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    from src.app.component_check import _temp_root

    assert _temp_root() == tmp_path / "data" / "tmp"
    assert (tmp_path / "data" / "tmp").is_dir()


def test_corrupted_resource_is_detected_by_verify_and_repaired(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    item = component(tmp_path)
    folder = catalog.install(item)
    assert catalog.ready(item)
    (folder / "weights.bin").write_bytes(b"wrong")
    assert catalog.ready(item)
    assert catalog.verify(item)["ok"] is False
    catalog.invalidate(item)
    assert not catalog.ready(item)
    assert catalog.install(item).joinpath("weights.bin").read_bytes() == b"model"
    assert catalog.ready(item)


def test_ready_trusts_marker_without_inventory_walk_or_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    monkeypatch.setattr(catalog, "validate_component", lambda *args: None)
    item = component(tmp_path, check="onnx")
    folder = catalog.install(item)
    marker = json.loads((folder / "component.json").read_text(encoding="utf-8"))
    marker.pop("requirements", None)
    marker["checker"] = "old-build"
    (folder / "component.json").write_text(json.dumps(marker), encoding="utf-8")

    monkeypatch.setattr(downloads, "digest", lambda *_: (_ for _ in ()).throw(AssertionError("hash")))
    assert catalog.ready(item)
    assert catalog.installed(item)


def test_failed_candidate_preserves_old_pointer(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    old = component(tmp_path)
    old_folder = catalog.install(old)
    new = component(tmp_path, b"new model", "onnx")
    monkeypatch.setattr("src.app.component_check.probe", lambda *args: (_ for _ in ()).throw(RuntimeError("probe failed")))
    with pytest.raises(RuntimeError, match="probe"):
        catalog.install(new)
    assert catalog.directory(old) == old_folder
    assert catalog.ready(old)
    assert not catalog.ready(new)


def test_zip_paths_are_bounded(tmp_path):
    for path in ("../outside", "/absolute", "C:/outside", "folder/../../outside"):
        with pytest.raises(ValueError):
            catalog.safe_path(tmp_path, path)
