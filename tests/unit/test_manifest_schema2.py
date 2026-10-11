"""Манифест schema 2: сборка и валидация полноты (офлайн)."""

from __future__ import annotations

from scripts.manifest_tools import build_manifest, merge_entries, validate_manifest

URL_BASE = "https://github.com/Jawerka/image-localization-tool/releases/download"


def _file(
    name: str = "torch-2.11.0+cpu-cp310-cp310-win_amd64.whl",
    *,
    sha: str = "a" * 64,
    size: int = 100,
    url: str = "https://download.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp310-cp310-win_amd64.whl",
) -> dict:
    return {"name": name, "url": url, "sha256": sha, "size_bytes": size}


def _record(files: list[dict] | None = None, **over) -> dict:
    item = _file()
    record = {
        "id": "torch-cpu",
        "title": "PyTorch CPU (LaMa)",
        "kind": "torch",
        "os": "win",
        "arch": "x64",
        "python": "310",
        "version": "2.11.0+cpu",
        "format": "wheels",
        "size_bytes": item["size_bytes"],
        "files": [item] if files is None else files,
    }
    record.update(over)
    return record


def test_build_manifest_schema2_valid() -> None:
    manifest = build_manifest("1.0.1", [_record()], URL_BASE)
    assert manifest["schema"] == 2
    assert manifest["packs"][0]["format"] == "wheels"
    assert validate_manifest(manifest) == []


def test_validate_catches_sum_mismatch() -> None:
    manifest = build_manifest("1.0.1", [_record()], URL_BASE)
    manifest["packs"][0]["size_bytes"] = 101
    issues = validate_manifest(manifest)
    assert any("сумме" in issue for issue in issues)


def test_validate_catches_bad_sha_empty_files_and_archive() -> None:
    bad_sha = build_manifest("1.0.1", [_record(files=[_file(sha="xyz")])], URL_BASE)
    assert any("sha256" in issue for issue in validate_manifest(bad_sha))

    empty = {
        "schema": 2,
        "packs": [_record(files=[])],
    }
    assert any("files пуст" in issue for issue in validate_manifest(empty))

    archive = {
        "schema": 2,
        "packs": [
            {
                "id": "argos",
                "title": "argos",
                "kind": "argos",
                "os": "win",
                "python": "310",
                "url": "https://example/argos.7z",
                "sha256": "",
                "size_bytes": 5,
            }
        ],
    }
    assert any("sha256" in issue for issue in validate_manifest(archive))


def test_build_manifest_legacy_archive_gets_release_url() -> None:
    record = {
        "id": "argos",
        "title": "Argos",
        "kind": "argos",
        "os": "win",
        "python": "310",
        "version": "1.0",
        "file": "ilt-runtime-argos-win-x64-py310.7z",
        "sha256": "b" * 64,
        "size_bytes": 5,
    }
    manifest = build_manifest("1.0.1", [record], URL_BASE)
    entry = manifest["packs"][0]
    assert entry["url"] == f"{URL_BASE}/v1.0.1/ilt-runtime-argos-win-x64-py310.7z"
    assert validate_manifest(manifest) == []


def test_merge_entries_overrides_by_id_os() -> None:
    base = build_manifest("1.0.1", [_record()], URL_BASE)["packs"]
    overlay = build_manifest(
        "1.0.1",
        [_record(files=[_file(size=200)], size_bytes=200)],
        URL_BASE,
    )["packs"]
    merged = merge_entries(base, overlay)
    assert len(merged) == 1
    assert merged[0]["size_bytes"] == 200
