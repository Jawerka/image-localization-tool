"""Генератор локов: разбор отчёта pip и записи files[] (офлайн-фикстуры)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import build_runtime_locks as locks

TORCH_URL = "https://download.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp310-cp310-win_amd64.whl"
SYMPY_URL = "https://files.pythonhosted.org/packages/x/sympy-1.14.0-py3-none-any.whl"
VCS_URL = "https://github.com/argosopentech/argos-translate.git"


def _report(items: list[tuple[str, str, str, bool]]) -> dict:
    """items: (name, version, url, is_vcs)."""
    install = []
    for name, version, url, is_vcs in items:
        info: dict = {"url": url}
        if is_vcs:
            info["vcs_info"] = {"vcs": "git", "commit_id": "x" * 40}
        else:
            info["archive_info"] = {"hashes": {"sha256": "a" * 64}}
        install.append(
            {"metadata": {"name": name, "version": version}, "download_info": info}
        )
    return {"install": install}


def _fake_pip(monkeypatch, report: dict) -> None:
    def fake(args: list[str]) -> None:
        if "--report" in args:
            path = Path(args[args.index("--report") + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report), encoding="utf-8")

    monkeypatch.setattr(locks, "_run_pip", fake)


def test_resolve_pins_splits_vcs_and_wheels(monkeypatch, tmp_path) -> None:
    report = _report(
        [
            ("torch", "2.11.0+cpu", TORCH_URL, False),
            ("sympy", "1.14.0", SYMPY_URL, False),
            ("argostranslate", "1.11.1", VCS_URL, True),
        ]
    )
    _fake_pip(monkeypatch, report)
    lock_pins, download_pins, top_version, expected = locks.resolve_pins("torch-cpu", tmp_path)
    assert top_version == "2.11.0+cpu"
    assert "argostranslate==1.11.1" in lock_pins
    assert "argostranslate==1.11.1" not in download_pins
    assert len(download_pins) == 2
    assert "torch-2.11.0+cpu-cp310-cp310-win_amd64.whl" in expected
    assert expected["torch-2.11.0+cpu-cp310-cp310-win_amd64.whl"]["url"] == TORCH_URL


def test_name_version_from_url() -> None:
    assert locks._name_version_from_url(TORCH_URL) == ("torch", "2.11.0+cpu")
    assert locks._name_version_from_url("https://example.com/README") == ("", "")


def test_hosted_entry_url_and_hash(tmp_path) -> None:
    wheel = tmp_path / "argostranslate-1.11.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel-bytes")
    entry = locks.hosted_entry(wheel, "https://github.com/o/r/releases/download")
    assert entry["url"] == (
        "https://github.com/o/r/releases/download/"
        "argostranslate-1.11.1-py3-none-any.whl"
    )
    assert entry["sha256"] == hashlib.sha256(b"wheel-bytes").hexdigest()
    assert entry["size_bytes"] == 11


def test_build_record_sums_files_and_driver_min() -> None:
    files = [
        {"name": "a.whl", "url": "https://x/a.whl", "sha256": "a" * 64, "size_bytes": 3},
        {"name": "b.whl", "url": "https://x/b.whl", "sha256": "b" * 64, "size_bytes": 4},
    ]
    record = locks.build_record("torch-cu128", "win", "310", "2.11.0+cu128", files)
    assert record["size_bytes"] == 7
    assert record["driver_min"] == 570
    assert record["format"] == "wheels"
    assert record["arch"] == "x64"


def test_lock_text_sorted_pins_and_header() -> None:
    text = locks.lock_text("argos", "win", "310", ["b==1", "a==2"])
    lines = text.strip().splitlines()
    assert lines[0].startswith("# python 3.10, argos, win")
    assert lines[1:] == ["b==1", "a==2"]
