"""Полный профиль не выбирает CUDA и не подмешивает личное состояние."""

import json

import pytest


def test_distribution_selections():
    from src.app.distribution import selections

    values = selections()
    assert {(v["source_lang"], v["target_lang"]) for v in values} == {("en", "ru"), ("ru", "en")}
    assert all(v["device"] == "cpu" and v["translator_backend"] == "argos" for v in values)


def test_verify_never_installs(monkeypatch):
    from src.app import distribution, preparation

    monkeypatch.setattr(preparation, "plan", lambda _: {"state": "idle", "items": [], "total": 1})
    monkeypatch.setattr(preparation.Manager, "start", lambda *_: pytest.fail("Не должно быть установки"))
    with pytest.raises(RuntimeError, match="не подготовлен"):
        distribution.verify()


def test_seed_does_not_overwrite_settings(tmp_path, monkeypatch):
    from src.app import distribution

    monkeypatch.setattr(distribution, "install_root", lambda: tmp_path)
    (tmp_path / "distribution.json").write_text(json.dumps({"profile": "cpu-full"}))
    root = tmp_path / "data"
    root.mkdir()
    path = root / "settings.json"
    path.write_text('{"theme":"light"}')
    distribution.seed_data(root)
    assert path.read_text() == '{"theme":"light"}'


def test_seed_full_offline_defaults(tmp_path, monkeypatch):
    from src.app import distribution

    monkeypatch.setattr(distribution, "install_root", lambda: tmp_path)
    (tmp_path / "distribution.json").write_text(json.dumps({"profile": "cpu-full"}))
    root = tmp_path / "data"
    root.mkdir()
    distribution.seed_data(root)
    settings = json.loads((root / "settings.json").read_text())
    assert settings["translator_backend"] == "argos"
    assert settings["ocr_backend"] == "rapid"
    assert settings["device"] == "cpu"
    assert settings["first_run_complete"] is True
