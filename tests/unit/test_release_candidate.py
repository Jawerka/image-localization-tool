"""Публикация принимает только тот комплект, который прошёл подготовку и smoke."""

import json

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
    assert "docker-cpu-full.zip" in str(error.value)
    assert "windows-x64-portable-cpu-full.zip" in str(error.value)
    assert "GHCR-DIGEST.txt" in str(error.value)


def test_source_digest_covers_container_build(tmp_path):
    source(tmp_path)
    before = release_candidate.source_digest(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM example")
    assert release_candidate.source_digest(tmp_path) != before


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


def _passport(**overrides) -> dict:
    payload = {
        "kind": "ilt-acceptance-passport",
        "version": "1.0.1",
        "source_sha": "abc123",
        "artifact_sha256": "def456",
        "environment": "windows-ci",
        "checks": [
            {
                "id": "R01",
                "status": "accepted",
                "command": "pytest tests/unit/test_release_candidate.py",
                "result": "pass",
                "constraints": "",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_passport_rejects_substituted_sha():
    passport = _passport()
    with pytest.raises(ValueError, match="SHA исходников"):
        release_candidate.validate_passport(
            passport,
            source_sha="other",
            version="1.0.1",
            artifact_sha256="def456",
            required_ids=["R01"],
        )


def test_passport_rejects_legacy_acceptance_and_failed_required():
    with pytest.raises(ValueError, match="1.0.5"):
        release_candidate.validate_passport(
            _passport(version="1.0.5"),
            source_sha="abc123",
            version="1.0.5",
        )
    with pytest.raises(ValueError, match="1.1.0"):
        release_candidate.validate_passport(
            _passport(version="1.1.0"),
            source_sha="abc123",
            version="1.1.0",
        )
    failed = _passport(checks=[{
        "id": "R01",
        "status": "deferred",
        "command": "pytest",
        "result": "skip",
    }])
    with pytest.raises(ValueError, match="не принята"):
        release_candidate.validate_passport(
            failed,
            source_sha="abc123",
            version="1.0.1",
            required_ids=["R01"],
        )
    release_candidate.validate_passport(
        _passport(),
        source_sha="abc123",
        version="1.0.1",
        artifact_sha256="def456",
        required_ids=["R01"],
    )


def test_passport_skip_is_not_success():
    skipped = _passport(checks=[{
        "id": "P01",
        "status": "tested",
        "command": "manual",
        "result": "skipped",
    }])
    with pytest.raises(ValueError, match="пропущ"):
        release_candidate.validate_passport(
            skipped,
            source_sha="abc123",
            version="1.0.1",
            required_ids=["P01"],
        )


def test_passport_requires_full_asset_checksums_and_digest():
    assets = [
        {"name": "a.zip", "sha256": "aaa", "size": 1},
        {"name": "b.zip", "sha256": "bbb", "size": 2},
        {"name": "GHCR-DIGEST.txt", "sha256": "ccc", "size": 3},
    ]
    digest = "ghcr.io/jawerka/image-localization-tool@sha256:" + ("a" * 64)
    passport = _passport(
        artifact_sha256="aaa",
        assets=assets,
        image_digest=digest,
        checks=[{
            "id": "P05",
            "status": "accepted",
            "command": "docker pull",
            "result": "pass",
        }],
    )
    release_candidate.validate_passport(
        passport,
        source_sha="abc123",
        version="1.0.1",
        artifact_sha256="aaa",
        required_ids=["P05"],
        assets=assets,
        image_digest=digest,
    )
    changed = [dict(assets[0], sha256="other"), assets[1], assets[2]]
    with pytest.raises(ValueError, match="SHA256"):
        release_candidate.validate_passport(
            passport,
            source_sha="abc123",
            version="1.0.1",
            assets=changed,
            image_digest=digest,
            required_ids=["P05"],
        )
    with pytest.raises(ValueError, match="Digest"):
        release_candidate.validate_passport(
            passport,
            source_sha="abc123",
            version="1.0.1",
            assets=assets,
            image_digest=digest.replace("a", "b", 1),
            required_ids=["P05"],
        )


def test_passport_rejects_implemented_blocked():
    checks = [
        {
            "id": check_id,
            "status": "implemented",
            "command": "manual",
            "result": "blocked-no-run",
        }
        for check_id in release_candidate.REQUIRED_CHECK_IDS
    ]
    blocked = _passport(checks=checks)
    with pytest.raises(ValueError, match="не принята"):
        release_candidate.validate_passport(
            blocked,
            source_sha="abc123",
            version="1.0.1",
            required_ids=list(release_candidate.REQUIRED_CHECK_IDS),
        )
