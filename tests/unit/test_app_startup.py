"""Старт приложения не читает системное хранилище ключей."""

import importlib

from src.app import desktop, runtime


def test_start_leaves_api_key_file_alone(monkeypatch, tmp_path):
    entry = importlib.import_module("src.app.__main__")
    monkeypatch.setattr(entry, "prepare_logging", lambda: tmp_path / "app.log")
    monkeypatch.setattr(runtime, "startup", lambda: [])
    monkeypatch.setattr(desktop, "launch", lambda _args: 0)
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))

    assert entry.main([]) == 0
    assert not (tmp_path / "data" / "llm-api-key.txt").exists()
