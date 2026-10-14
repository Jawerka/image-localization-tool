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


def test_publish_requires_manual_smoke(tmp_path):
    with pytest.raises(ValueError, match="ручную"):
        release_candidate.verify(tmp_path, tmp_path, {"checks_passed": True})


def test_candidate_requires_all_platforms(tmp_path):
    with pytest.raises(ValueError, match="Неполный"):
        release_candidate.create(tmp_path, tmp_path, "1.0.1", "v1.0.1")
