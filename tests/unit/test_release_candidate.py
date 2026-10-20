"""Публикация принимает только тот комплект, который прошёл подготовку и smoke."""

import json
from pathlib import Path

import pytest

from scripts import release_candidate
from src.app.downloads import digest


def source(root):
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/__init__.py").write_text('__version__ = "1.0.1"\n')
    (root / "ImageLocalizationTool.spec").write_text("build")


def test_publish_rejects_modified_asset_or_source(tmp_path):
    source(tmp_path)
    assets = tmp_path / "dist"
    assets.mkdir()
    path = assets / "app.zip"
    path.write_bytes(b"tested")
    report = {"version": "1.0.1", "source_sha": release_candidate.source_digest(tmp_path),
              "checks_passed": True, "manual_smoke_passed": True,
              "assets": [{"name": path.name, "sha256": digest(path), "size": 6}]}
    release_candidate.verify(tmp_path, assets, report)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="файл"):
        release_candidate.verify(tmp_path, assets, report)
    path.write_bytes(b"tested")
    (tmp_path / "src/new.py").write_text("changed")
    with pytest.raises(ValueError, match="Исходники"):
        release_candidate.verify(tmp_path, assets, report)


def test_source_digest_ignores_generated_flutter_ephemeral(tmp_path):
    source(tmp_path)
    (tmp_path / "apps/desktop/windows/runner").mkdir(parents=True)
    (tmp_path / "apps/desktop/windows/runner/main.cpp").write_text("code")
    (tmp_path / "apps/desktop/pubspec.yaml").write_text("name: x")
    (tmp_path / "apps/desktop/pubspec.lock").write_text("lock")
    before = release_candidate.source_digest(tmp_path)
    ephemeral = tmp_path / "apps/desktop/windows/flutter/ephemeral"
    ephemeral.mkdir(parents=True)
    (ephemeral / "flutter_windows.dll").write_bytes(b"generated")
    (ephemeral / "generated_config.cmake").write_text("generated")
    assert release_candidate.source_digest(tmp_path) == before


def test_publish_requires_manual_smoke(tmp_path):
    with pytest.raises(ValueError, match="ручную"):
        release_candidate.verify(tmp_path, tmp_path, {"checks_passed": True})


def test_candidate_requires_all_platforms(tmp_path):
    with pytest.raises(ValueError, match="Неполный") as error:
        release_candidate.create(tmp_path, tmp_path, "1.0.1", "v1.0.1")
    assert "windows-x64-portable.zip" in str(error.value)
    assert "setup.exe" not in str(error.value)


def test_build_proof_rejects_stale_binary_and_source(tmp_path):
    source(tmp_path)
    (tmp_path / "build").mkdir()
    artifact = tmp_path / "portable.zip"
    artifact.write_bytes(b"built")
    (tmp_path / "server.zip").write_bytes(b"built")
    proof = {"source_sha": release_candidate.source_digest(tmp_path),
             "assets": [{"name": name, "sha256": digest(tmp_path / name)}
                        for name in ("portable.zip", "server.zip")]}
    (tmp_path / "build/build-source.json").write_text(json.dumps(proof))
    release_candidate.verify_build(tmp_path, tmp_path)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="изменён"):
        release_candidate.verify_build(tmp_path, tmp_path)
    artifact.write_bytes(b"built")
    (tmp_path / "src/app/new.py").write_text("new source")
    with pytest.raises(ValueError, match="исходников"):
        release_candidate.verify_build(tmp_path, tmp_path)
