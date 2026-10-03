"""Статус моделей и докачка через подмену urlopen. Сеть не используется."""

import json
import urllib.request
from pathlib import Path

from scripts.setup_models import FONT_URL as SETUP_FONT_URL
from scripts.setup_models import LAMA_URL as SETUP_LAMA_URL

from src.app.model_manager import (
    FONT_FILENAME,
    FONT_URL,
    LAMA_FILENAME,
    LAMA_URL,
    check_llm,
    dest_dir,
    download,
    status,
)


def test_font_goes_beside_program_and_models_follow_override(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.model_manager.install_root", lambda: tmp_path)
    monkeypatch.setattr("src.app.model_manager.models_dir", lambda override=None: Path(override) if override else tmp_path / "models")
    assert dest_dir("font") == tmp_path / "fonts"
    custom = tmp_path / "custom"
    assert dest_dir("lama", str(custom)) == custom
    assert dest_dir("detector", "  ") == tmp_path / "models"


def test_urls_match_setup_script():
    assert LAMA_URL == SETUP_LAMA_URL
    assert FONT_URL == SETUP_FONT_URL


def test_status_on_temp_dir(tmp_path, monkeypatch):
    def fake_model(name, override=None):
        root = Path(override) if override else tmp_path
        return root / name

    def fake_font(name):
        return tmp_path / name

    monkeypatch.setattr("src.app.model_manager.resolve_model", fake_model)
    monkeypatch.setattr("src.app.model_manager.resolve_font", fake_font)

    report = status(str(tmp_path))
    assert report["detector"]["present"] is False
    assert report["lama"]["present"] is False
    assert report["font"]["present"] is False

    (tmp_path / "ogkalu-detector-v4-s_int8.onnx").write_bytes(b"onnx")
    (tmp_path / LAMA_FILENAME).write_bytes(b"pt")
    (tmp_path / FONT_FILENAME).write_bytes(b"otf")
    report = status(str(tmp_path))
    assert report["detector"]["present"] is True
    assert report["detector"]["path"].endswith("ogkalu-detector-v4-s_int8.onnx")
    assert report["lama"]["present"] is True
    assert Path(report["lama"]["path"]).parent == tmp_path
    assert report["font"]["present"] is True

    (tmp_path / LAMA_FILENAME).write_bytes(b"")
    assert status(str(tmp_path))["lama"]["present"] is False


class _Response:
    def __init__(self, data: bytes, headers=None):
        self._data = data
        self._done = False
        self.headers = headers or {"Content-Length": str(len(data))}

    def read(self, _size=-1):
        if self._done:
            return b""
        self._done = True
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_download_uses_urlopen_and_skips_existing(tmp_path, monkeypatch):
    seen = {}
    progress_calls = []

    def fake_urlopen(request, timeout=120):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response(b"model")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    path = download("lama", tmp_path, progress=lambda done, total: progress_calls.append((done, total)))
    assert path.name == LAMA_FILENAME
    assert path.read_bytes() == b"model"
    assert seen["url"] == LAMA_URL
    assert (len(b"model"), len(b"model")) in progress_calls

    def boom(*_args, **_kwargs):
        raise AssertionError("сеть")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    again = download("lama", tmp_path)
    assert again.read_bytes() == b"model"

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    font = download("font", tmp_path)
    assert font.name == FONT_FILENAME
    detector = download("detector", tmp_path / "models")
    assert detector.name == "ogkalu-detector-v4-s_int8.onnx"


def test_check_llm_without_network(monkeypatch):
    empty = check_llm("  ")
    assert empty["ok"] is False
    assert empty["reason"] == "empty"
    assert empty["models"] == []

    seen = {}

    def fake_urlopen(request, timeout=10):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        body = json.dumps({"data": [{"id": "qwen"}]}).encode("utf-8")
        return _Response(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = check_llm("http://example/v1", api_key="secret")
    assert result == {"ok": True, "models": ["qwen"]}
    assert seen["url"] == "http://example/v1/models"
    assert seen["timeout"] == 10
    assert seen["auth"] == "Bearer secret"

    def fail(*_args, **_kwargs):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    failed = check_llm("http://example/v1")
    assert failed["ok"] is False
    assert failed["models"] == []
