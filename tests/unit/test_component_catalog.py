"""Проверка целостности и транзакций внешних ресурсов."""

import json

import pytest

from src.app import component_catalog as catalog, downloads


def component(tmp_path, payload=b"model", check=""):
    path = tmp_path / "weights.bin"
    path.write_bytes(payload)
    return catalog.Component("demo", "demo", "model", (downloads.Artifact(path.name, (path.as_uri(),),
        downloads.digest(path), len(payload)),), check)


def test_corrupted_resource_is_not_ready_and_can_be_repaired(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "install"))
    item = component(tmp_path)
    folder = catalog.install(item)
    assert catalog.ready(item)
    (folder / "weights.bin").write_bytes(b"wrong")
    assert not catalog.ready(item)
    assert catalog.install(item).joinpath("weights.bin").read_bytes() == b"model"
    assert catalog.ready(item)


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
