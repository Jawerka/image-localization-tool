"""Портативный .ilt.zip: pages/, res/, порядок, устойчивость."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PIL import Image

from src.app.document import PageDocument
from src.app.portable_project import (
    SCHEMA_VERSION,
    PortableProjectError,
    is_portable_package,
    pack_project,
    resolve_archive_open_kind,
    unpack_project,
)
from src.app.store import ProjectStore
from src.models import TextRegion


def _png(path: Path, color=(30, 60, 90)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), color).save(path)


def test_reorder_and_pack_prefixes(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _png(a, (10, 20, 30))
    _png(b, (40, 50, 60))
    pages = store.add_sources(project["id"], [a, b])
    first, second = pages[0], pages[1]

    doc = store.read_document(project["id"], first["id"])
    doc.regions = [TextRegion(id=1, bbox=(0, 0, 4, 4), text="hi", translation="привет")]
    store.write_document(project["id"], first["id"], doc, base_version=1)

    store.reorder_pages(project["id"], [second["id"], first["id"]])
    dest = tmp_path / "demo.ilt.zip"
    packed = pack_project(store, project["id"], dest)

    with zipfile.ZipFile(packed.path) as archive:
        names = set(archive.namelist())
        assert "project.json" in names
        assert "pages/0001_b.png" in names
        assert "pages/0002_a.png" in names
        assert not any(name.startswith("pages/") and ".mask." in name for name in names)
        manifest = json.loads(archive.read("project.json").decode("utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert [item["name"] for item in manifest["pages"]] == ["b.png", "a.png"]
    assert manifest["pages"][1]["document"]["regions"][0]["translation"] == "привет"

    loaded = unpack_project(store, packed.path)
    assert [item["name"] for item in loaded.project["pages"]] == ["b.png", "a.png"]
    restored = store.read_document(loaded.project["id"], loaded.project["pages"][1]["id"])
    assert restored.regions[0].translation == "привет"
    assert Path(loaded.project["pages"][0]["source_path"]).is_file()


def test_pack_round_trip_artifacts_in_res(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "cover.png"
    _png(image)
    page = store.add_sources(project["id"], [image])[0]
    pid = project["id"]
    page_id = page["id"]

    store.save_image(pid, page_id, "mask", Image.new("L", (40, 20), 255))
    store.save_image(pid, page_id, "result", Image.new("RGB", (40, 20), (1, 2, 3)))

    packed = pack_project(store, pid, tmp_path / "pkg.ilt.zip")
    with zipfile.ZipFile(packed.path) as archive:
        names = set(archive.namelist())
        assert "pages/0001_cover.png" in names
        assert "res/0001_cover.mask.png" in names
        assert "res/0001_cover.result.png" in names
        assert "pages/0001_cover.mask.png" not in names

    loaded = unpack_project(store, packed.path)
    new_id = loaded.project["id"]
    new_page = loaded.project["pages"][0]["id"]
    assert store.image_path(new_id, new_page, "mask").is_file()
    assert store.image_path(new_id, new_page, "result").is_file()


def test_pack_skips_bad_document_still_writes_zip(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    good = tmp_path / "ok.png"
    bad = tmp_path / "bad.png"
    _png(good, (1, 2, 3))
    _png(bad, (4, 5, 6))
    pages = store.add_sources(project["id"], [good, bad])
    pid = project["id"]
    bad_id = pages[1]["id"]
    page_json = store.page_dir(pid, bad_id) / "page.json"
    page_json.write_text("{not json", encoding="utf-8")

    packed = pack_project(store, pid, tmp_path / "partial.ilt.zip")
    assert packed.path.is_file()
    assert any("document" in item for item in packed.warnings)

    with zipfile.ZipFile(packed.path) as archive:
        manifest = json.loads(archive.read("project.json").decode("utf-8"))
    assert len(manifest["pages"]) == 2
    assert manifest["pages"][0]["document"] is not None
    assert manifest["pages"][1]["document"] is None


def test_load_v1_without_res(tmp_path):
    store = ProjectStore(tmp_path / "data")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "legacy.ilt.zip"
    manifest = {
        "kind": "ilt-project",
        "schema_version": 1,
        "name": "Legacy",
        "source_lang": "en",
        "target_lang": "ru",
        "pages": [
            {
                "id": "abcd1234",
                "name": "p.png",
                "status": "idle",
                "chapter": "",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=1).to_dict(),
            }
        ],
    }
    with zipfile.ZipFile(dest, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
        archive.write(image, arcname="pages/0001_p.png")

    loaded = unpack_project(store, dest)
    assert len(loaded.project["pages"]) == 1


def test_unpack_rejects_plain_zip(tmp_path):
    store = ProjectStore(tmp_path / "data")
    plain = tmp_path / "chapter.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("page.png", b"not-an-image")
    try:
        unpack_project(store, plain)
        raised = False
    except PortableProjectError:
        raised = True
    assert raised
    assert store.list_projects() == []


def test_is_portable_package_peek(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image)
    store.add_sources(project["id"], [image])
    packed = pack_project(store, project["id"], tmp_path / "pkg.ilt.zip")
    assert is_portable_package(packed.path)
    assert resolve_archive_open_kind(packed.path) == "portable"

    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("001.png", b"not-a-png")
    assert not is_portable_package(plain)
    assert resolve_archive_open_kind(plain) == "chapter"


def test_broken_ilt_manifest_raises(tmp_path):
    broken = tmp_path / "broken.zip"
    manifest = {"kind": "ilt-project", "schema_version": 2, "pages": []}
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest).encode("utf-8"))
    try:
        resolve_archive_open_kind(broken)
        raised = False
    except PortableProjectError:
        raised = True
    assert raised


def test_pack_empty_project_fails(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Пусто", "en", "ru")
    try:
        pack_project(store, project["id"], tmp_path / "empty.ilt.zip")
        raised = False
    except PortableProjectError:
        raised = True
    assert raised
