"""Гейт релиза: структура, ключ кэша и разбор HEAD (без сети)."""

from __future__ import annotations

import urllib.error
from pathlib import Path

from scripts import check_release as gate
from scripts.manifest_tools import build_manifest

URL = "https://download.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp310-cp310-win_amd64.whl"
URL_BASE = "https://github.com/Jawerka/image-localization-tool/releases/download"


def _manifest() -> dict:
    record = {
        "id": "torch-cpu",
        "title": "PyTorch CPU (LaMa)",
        "kind": "torch",
        "os": "win",
        "arch": "x64",
        "python": "310",
        "version": "2.11.0+cpu",
        "format": "wheels",
        "size_bytes": 10,
        "files": [{"name": "torch.whl", "url": URL, "sha256": "a" * 64, "size_bytes": 10}],
    }
    return build_manifest("1.0.1", [record], URL_BASE)


def test_url_jobs_use_files_and_archives() -> None:
    jobs = gate._url_jobs(_manifest())
    assert jobs == [(URL, 10, "torch-cpu/win torch.whl")]
    archive = {
        "packs": [
            {
                "id": "argos",
                "os": "win",
                "url": "https://example/argos.7z",
                "size_bytes": 5,
            }
        ]
    }
    assert gate._url_jobs(archive) == [("https://example/argos.7z", 5, "argos/win archive")]


def test_cache_key_stable_and_sensitive(tmp_path: Path) -> None:
    manifest = tmp_path / "ilt-runtime-manifest-1.0.1.json"
    manifest.write_text("{}", encoding="utf-8")
    setup = tmp_path / "ImageLocalizationTool-1.0.1-windows-x64-setup.exe"
    setup.write_bytes(b"setup")
    first = gate.cache_key(tmp_path, manifest)
    assert gate.cache_key(tmp_path, manifest) == first
    setup.write_bytes(b"setup-2")
    assert gate.cache_key(tmp_path, manifest) != first


def test_cache_key_manifest_only(tmp_path: Path) -> None:
    manifest = tmp_path / "ilt-runtime-manifest-1.0.1.json"
    manifest.write_text("{}", encoding="utf-8")
    key = gate.cache_key(tmp_path, manifest)
    assert len(key) == 64
    missing = tmp_path / "nope" / "ilt-runtime-manifest-9.9.9.json"
    assert gate.cache_key(tmp_path, missing) == "empty"


class _Resp:
    def __init__(self, status: int = 200, headers: dict | None = None) -> None:
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def test_head_check_ok_and_no_length(monkeypatch) -> None:
    monkeypatch.setattr(
        gate.urllib.request, "urlopen", lambda *a, **k: _Resp(200, {"Content-Length": "10"})
    )
    ok, _detail, length = gate.head_check("https://x/a.whl", 5)
    assert ok and length == 10

    monkeypatch.setattr(gate.urllib.request, "urlopen", lambda *a, **k: _Resp(200, {}))
    ok, _detail, length = gate.head_check("https://x/a.whl", 5)
    assert ok and length is None


def test_head_check_http_error(monkeypatch) -> None:
    def raise_http(*args, **kwargs):
        raise urllib.error.HTTPError("https://x/a.whl", 404, "not found", None, None)

    monkeypatch.setattr(gate.urllib.request, "urlopen", raise_http)
    ok, detail, length = gate.head_check("https://x/a.whl", 5)
    assert not ok and "404" in detail and length is None


def test_check_urls_flags_content_length_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        gate.urllib.request, "urlopen", lambda *a, **k: _Resp(200, {"Content-Length": "9"})
    )
    failures, warnings = gate.check_urls(_manifest(), timeout=5)
    assert warnings == []
    assert failures and "Content-Length 9" in failures[0]


def test_check_urls_warns_without_length(monkeypatch) -> None:
    monkeypatch.setattr(gate.urllib.request, "urlopen", lambda *a, **k: _Resp(200, {}))
    failures, warnings = gate.check_urls(_manifest(), timeout=5)
    assert failures == []
    assert warnings and "нет Content-Length" in warnings[0]
