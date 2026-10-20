"""Старт приложения: миграция ключа и диагностический запуск обновления."""

import importlib

from src.app import desktop, runtime


def _prepare_startup(monkeypatch, tmp_path):
    entry = importlib.import_module("src.app.__main__")
    monkeypatch.setattr(entry, "prepare_logging", lambda: tmp_path / "app.log")
    monkeypatch.setattr(runtime, "startup", lambda: [])
    monkeypatch.setattr(desktop, "launch", lambda _args: 0)
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    return entry


def test_normal_start_migrates_keyring(monkeypatch, tmp_path, isolated_keyring):
    isolated_keyring[("ImageLocalizationTool", "llm")] = "synthetic-key"
    monkeypatch.delenv("ILT_SKIP_KEYRING_MIGRATION", raising=False)
    entry = _prepare_startup(monkeypatch, tmp_path)

    assert entry.main([]) == 0
    assert isolated_keyring == {}
    assert (tmp_path / "data" / "llm-api-key.txt").read_text(encoding="utf-8").strip() == "synthetic-key"


def test_probe_start_keeps_keyring(monkeypatch, tmp_path, isolated_keyring):
    isolated_keyring[("ImageLocalizationTool", "llm")] = "synthetic-key"
    monkeypatch.setenv("ILT_SKIP_KEYRING_MIGRATION", "1")
    entry = _prepare_startup(monkeypatch, tmp_path)

    assert entry.main([]) == 0
    assert isolated_keyring == {("ImageLocalizationTool", "llm"): "synthetic-key"}
    assert not (tmp_path / "data" / "llm-api-key.txt").exists()
