"""Портативный .ilt.zip: pages/, res/, порядок, устойчивость."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from src.app.document import PageDocument
from src.app.portable_project import (
    SCHEMA_VERSION,
    PortableProjectError,
    _unique_import_name,
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
    snapshot = {
        "version": 1,
        "layout_key": "key",
        "font_size": 18,
        "font": "Heroika-Regular.otf",
        "lines": [["hi", 2, 3]],
    }
    doc.regions = [
        TextRegion(
            id=1,
            bbox=(0, 0, 4, 4),
            text="hi",
            translation="привет",
            layout_snapshot=snapshot,
        )
    ]
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
    assert manifest["pages"][1]["document"]["regions"][0]["layout_snapshot"]["font_size"] == 18

    loaded = unpack_project(store, packed.path)
    assert [item["name"] for item in loaded.project["pages"]] == ["b.png", "a.png"]
    restored = store.read_document(loaded.project["id"], loaded.project["pages"][1]["id"])
    assert restored.regions[0].translation == "привет"
    assert restored.regions[0].layout_snapshot == snapshot
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


def test_pack_unpack_preserves_editor_session(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _png(a)
    _png(b)
    pages = store.add_sources(project["id"], [a, b])
    editor = {
        "active_page_id": pages[1]["id"],
        "zoom": "fit-width",
        "scroll_left": 40,
        "scroll_top": 80,
    }
    packed = pack_project(store, project["id"], tmp_path / "sess.ilt.zip", editor=editor)
    with zipfile.ZipFile(packed.path) as archive:
        manifest = json.loads(archive.read("project.json").decode("utf-8"))
    assert manifest["editor"]["active_page_id"] == pages[1]["id"]
    assert manifest["editor"]["zoom"] == "fit-width"
    assert manifest["editor"]["scroll_left"] == 40
    assert manifest["editor"]["scroll_top"] == 80

    loaded = unpack_project(store, packed.path)
    assert loaded.editor is not None
    assert loaded.editor["active_page_id"] == pages[1]["id"]
    assert loaded.editor["zoom"] == "fit-width"
    assert loaded.editor["scroll_left"] == 40.0
    assert loaded.editor["scroll_top"] == 80.0


def _one_page(tmp_path: Path) -> tuple[ProjectStore, str, Path]:
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image, (8, 16, 24))
    store.add_sources(project["id"], [image])
    return store, project["id"], tmp_path / "pkg.ilt.zip"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock_final_replace(monkeypatch, dest: Path, *, fail_times: int | None):
    """PermissionError только на замене итогового ZIP. fail_times=None — всегда."""
    monkeypatch.setattr("src.app.store.time.sleep", lambda *_args, **_kwargs: None)
    real_replace = Path.replace
    calls = {"n": 0}

    def locked(self, target):
        if Path(target) == dest:
            calls["n"] += 1
            if fail_times is None or calls["n"] <= fail_times:
                raise PermissionError(13, "Отказано в доступе", str(target))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    return calls


def _temp_packages(dest: Path) -> list[Path]:
    prefix = f".{dest.name}."
    return [item for item in dest.parent.iterdir() if item.name.startswith(prefix)]


def test_pack_replace_permission_error_keeps_previous_sha256(tmp_path, monkeypatch):
    store, project_id, dest = _one_page(tmp_path)
    pack_project(store, project_id, dest)
    previous = _sha256(dest)

    _lock_final_replace(monkeypatch, dest, fail_times=None)
    try:
        pack_project(store, project_id, dest)
        raised = False
    except PermissionError:
        raised = True
    assert raised
    assert dest.is_file()
    assert _sha256(dest) == previous
    assert _temp_packages(dest) == []

    monkeypatch.undo()
    packed = pack_project(
        store,
        project_id,
        dest,
        editor={"active_page_id": "page", "zoom": "fit", "scroll_left": 0, "scroll_top": 0},
    )
    assert _sha256(dest) != previous
    assert is_portable_package(packed.path)
    loaded = unpack_project(store, packed.path)
    assert loaded.editor is not None
    assert loaded.editor["zoom"] == "fit"
    assert _temp_packages(dest) == []


def test_pack_replace_retries_then_overwrites(tmp_path, monkeypatch):
    store, project_id, dest = _one_page(tmp_path)
    pack_project(store, project_id, dest)
    previous = _sha256(dest)
    calls = _lock_final_replace(monkeypatch, dest, fail_times=2)

    packed = pack_project(
        store,
        project_id,
        dest,
        editor={"active_page_id": "page", "zoom": 1.5, "scroll_left": 1, "scroll_top": 2},
    )
    assert calls["n"] == 3
    assert _sha256(dest) != previous
    assert is_portable_package(packed.path)
    loaded = unpack_project(store, packed.path)
    assert loaded.editor is not None
    assert loaded.editor["zoom"] == 1.5
    assert _temp_packages(dest) == []


def test_pack_replace_failure_does_not_create_package(tmp_path, monkeypatch):
    store, project_id, dest = _one_page(tmp_path)
    _lock_final_replace(monkeypatch, dest, fail_times=None)
    try:
        pack_project(store, project_id, dest)
        raised = False
    except PermissionError:
        raised = True
    assert raised
    assert not dest.exists()
    assert _temp_packages(dest) == []


def _hand_package(dest: Path, pages: list[dict], files: dict[str, Path | bytes]) -> None:
    manifest = {
        "kind": "ilt-project",
        "schema_version": 2,
        "name": "Пакет",
        "source_lang": "en",
        "target_lang": "ru",
        "pages": pages,
    }
    with zipfile.ZipFile(dest, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest, ensure_ascii=False))
        for arcname, payload in files.items():
            if isinstance(payload, Path):
                archive.write(payload, arcname=arcname)
            else:
                archive.writestr(arcname, payload)


def test_unique_import_name_avoids_casefold_collision():
    taken = {"0001_pages_page.png"}
    name = _unique_import_name(1, "pages/Page.png", taken)
    assert name == "0001_pages_Page_2.png"
    assert name.casefold() not in {"0001_pages_page.png"}
    assert name.casefold() in taken


def test_unpack_keeps_same_basename_from_different_folders(tmp_path):
    store = ProjectStore(tmp_path / "data")
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    _png(red, (200, 10, 10))
    _png(blue, (10, 10, 200))
    dest = tmp_path / "same-name.ilt.zip"
    _hand_package(
        dest,
        [
            {
                "id": "aaa11111",
                "name": "page.png",
                "image": "pages/a/page.png",
                "document": PageDocument(version=1).to_dict(),
            },
            {
                "id": "bbb22222",
                "name": "page.png",
                "image": "pages/b/page.png",
                "document": PageDocument(version=1).to_dict(),
            },
        ],
        {"pages/a/page.png": red, "pages/b/page.png": blue},
    )
    loaded = unpack_project(store, dest)
    pages = loaded.project["pages"]
    assert len(pages) == 2
    first = Path(pages[0]["source_path"]).read_bytes()
    second = Path(pages[1]["source_path"]).read_bytes()
    assert first != second
    assert Path(pages[0]["source_path"]).name != Path(pages[1]["source_path"]).name


def test_unpack_case_differing_members_stay_separate(tmp_path):
    store = ProjectStore(tmp_path / "data")
    upper = tmp_path / "upper.png"
    lower = tmp_path / "lower.png"
    _png(upper, (1, 2, 3))
    _png(lower, (4, 5, 6))
    dest = tmp_path / "case.ilt.zip"
    _hand_package(
        dest,
        [
            {"id": "ccc33333", "name": "Page.png", "image": "pages/Page.png"},
            {"id": "ddd44444", "name": "page.png", "image": "pages/page.png"},
        ],
        {"pages/Page.png": upper, "pages/page.png": lower},
    )
    loaded = unpack_project(store, dest)
    paths = [Path(item["source_path"]) for item in loaded.project["pages"]]
    assert paths[0].read_bytes() != paths[1].read_bytes()
    assert paths[0].name.casefold() != paths[1].name.casefold() or paths[0].name != paths[1].name


def test_unpack_duplicate_id_does_not_create_project(tmp_path):
    store = ProjectStore(tmp_path / "data")
    existing = store.create_project("Живой", "en", "ru")
    image = tmp_path / "page.png"
    _png(image)
    dest = tmp_path / "dup.ilt.zip"
    page = {
        "id": "abcd1234",
        "name": "page.png",
        "image": "pages/0001_page.png",
        "document": PageDocument(version=1).to_dict(),
    }
    _hand_package(
        dest,
        [page, dict(page, name="other.png", image="pages/0002_page.png")],
        {"pages/0001_page.png": image, "pages/0002_page.png": image},
    )
    try:
        unpack_project(store, dest)
        raised = False
    except PortableProjectError:
        raised = True
    assert raised
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == existing["id"]


def test_unpack_skips_unsafe_image_member(tmp_path):
    store = ProjectStore(tmp_path / "data")
    image = tmp_path / "ok.png"
    _png(image, (9, 8, 7))
    dest = tmp_path / "unsafe.ilt.zip"
    _hand_package(
        dest,
        [
            {"id": "eee55555", "name": "bad.png", "image": "../secret.png"},
            {"id": "fff66666", "name": "ok.png", "image": "pages/0001_ok.png"},
        ],
        {"../secret.png": image, "pages/0001_ok.png": image},
    )
    loaded = unpack_project(store, dest)
    assert len(loaded.project["pages"]) == 1
    assert loaded.project["pages"][0]["name"] == "ok.png"
    assert any("небезопасный" in item for item in loaded.warnings)


def test_pack_unpack_preserves_auto_snapshot(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image)
    page = store.add_sources(project["id"], [image])[0]
    pid, page_id = project["id"], page["id"]
    auto = PageDocument(version=1, ocr_engine="auto-ocr")
    auto.regions = [
        TextRegion(id=1, bbox=(1, 2, 8, 9), text="auto", translation="авто"),
    ]
    store.write_auto(pid, page_id, auto)
    edited = store.read_document(pid, page_id)
    edited.ocr_engine = "edited"
    edited.regions = [
        TextRegion(id=1, bbox=(1, 2, 8, 9), text="auto", translation="правка"),
    ]
    store.write_document(pid, page_id, edited, base_version=1)
    store.save_image(pid, page_id, "mask", Image.new("L", (40, 20), 255))

    packed = pack_project(store, pid, tmp_path / "auto.ilt.zip")
    with zipfile.ZipFile(packed.path) as archive:
        manifest = json.loads(archive.read("project.json").decode("utf-8"))
        assert manifest["pages"][0]["auto"] == "res/0001_page.auto.json"
        assert "res/0001_page.auto.json" in archive.namelist()
        assert "res/0001_page.mask.png" in archive.namelist()

    loaded = unpack_project(store, packed.path)
    new_id = loaded.project["id"]
    new_page = loaded.project["pages"][0]["id"]
    restored_auto = store.read_auto(new_id, new_page)
    restored_doc = store.read_document(new_id, new_page)
    assert restored_auto.ocr_engine == "auto-ocr"
    assert restored_auto.regions[0].translation == "авто"
    assert restored_auto.regions[0].bbox == (1, 2, 8, 9)
    assert restored_doc.ocr_engine == "edited"
    assert restored_doc.regions[0].translation == "правка"
    assert store.image_path(new_id, new_page, "mask").is_file()


def test_unpack_missing_auto_does_not_copy_document(tmp_path):
    store = ProjectStore(tmp_path / "data")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "no-auto.ilt.zip"
    _hand_package(
        dest,
        [
            {
                "id": "abcd1234",
                "name": "p.png",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=2, ocr_engine="current").to_dict(),
            }
        ],
        {"pages/0001_p.png": image},
    )
    loaded = unpack_project(store, dest)
    page_id = loaded.project["pages"][0]["id"]
    assert store.read_document(loaded.project["id"], page_id).ocr_engine == "current"
    try:
        store.read_auto(loaded.project["id"], page_id)
        exists = True
    except FileNotFoundError:
        exists = False
    assert not exists


def test_unpack_broken_auto_keeps_document(tmp_path):
    store = ProjectStore(tmp_path / "data")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "bad-auto.ilt.zip"
    _hand_package(
        dest,
        [
            {
                "id": "abcd1234",
                "name": "p.png",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=1, ocr_engine="keep").to_dict(),
                "auto": "res/0001_p.auto.json",
            }
        ],
        {"pages/0001_p.png": image, "res/0001_p.auto.json": b"{not json"},
    )
    loaded = unpack_project(store, dest)
    page_id = loaded.project["pages"][0]["id"]
    assert store.read_document(loaded.project["id"], page_id).ocr_engine == "keep"
    assert any("auto" in item for item in loaded.warnings)
    try:
        store.read_auto(loaded.project["id"], page_id)
        exists = True
    except FileNotFoundError:
        exists = False
    assert not exists


def test_pack_missing_source_is_incomplete(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    kept = tmp_path / "kept.png"
    gone = tmp_path / "gone.png"
    _png(kept, (1, 2, 3))
    _png(gone, (4, 5, 6))
    pages = store.add_sources(project["id"], [kept, gone])
    Path(pages[1]["source_path"]).unlink()
    packed = pack_project(store, project["id"], tmp_path / "partial.ilt.zip")
    assert packed.complete is False
    assert packed.warnings
    with zipfile.ZipFile(packed.path) as archive:
        manifest = json.loads(archive.read("project.json").decode("utf-8"))
    assert len(manifest["pages"]) == 1
    assert manifest["pages"][0]["id"] == pages[0]["id"]


def test_unpack_rejects_schema_newer_than_supported(tmp_path):
    store = ProjectStore(tmp_path / "data")
    existing = store.create_project("Живой", "en", "ru")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "future.ilt.zip"
    manifest = {
        "kind": "ilt-project",
        "schema_version": 99,
        "name": "Будущее",
        "source_lang": "en",
        "target_lang": "ru",
        "pages": [
            {
                "id": "abcd1234",
                "name": "p.png",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=1).to_dict(),
            }
        ],
    }
    with zipfile.ZipFile(dest, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
        archive.write(image, arcname="pages/0001_p.png")
    try:
        unpack_project(store, dest)
        raised = False
    except PortableProjectError as exc:
        raised = True
        assert "99" in str(exc)
    assert raised
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == existing["id"]


def test_unpack_truncated_zip_does_not_create_project(tmp_path):
    store = ProjectStore(tmp_path / "data")
    existing = store.create_project("Живой", "en", "ru")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "ok.ilt.zip"
    _hand_package(
        dest,
        [
            {
                "id": "abcd1234",
                "name": "p.png",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=1).to_dict(),
            }
        ],
        {"pages/0001_p.png": image},
    )
    truncated = tmp_path / "trunc.ilt.zip"
    truncated.write_bytes(dest.read_bytes()[:32])
    try:
        unpack_project(store, truncated)
        raised = False
    except PortableProjectError:
        raised = True
    assert raised
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == existing["id"]


def test_unpack_broken_result_keeps_document(tmp_path):
    store = ProjectStore(tmp_path / "data")
    image = tmp_path / "p.png"
    _png(image)
    dest = tmp_path / "bad-result.ilt.zip"
    _hand_package(
        dest,
        [
            {
                "id": "abcd1234",
                "name": "p.png",
                "image": "pages/0001_p.png",
                "document": PageDocument(version=1, ocr_engine="keep").to_dict(),
                "result": "res/0001_p.result.png",
            }
        ],
        {"pages/0001_p.png": image, "res/0001_p.result.png": b"not a png"},
    )
    loaded = unpack_project(store, dest)
    page_id = loaded.project["pages"][0]["id"]
    assert store.read_document(loaded.project["id"], page_id).ocr_engine == "keep"
    assert any("повреждён" in item for item in loaded.warnings)
    assert not store.image_path(loaded.project["id"], page_id, "result").is_file()


def test_unpack_does_not_need_original_source_path(tmp_path):
    store = ProjectStore(tmp_path / "machine-a")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "orig.png"
    _png(image, (11, 22, 33))
    store.add_sources(project["id"], [image])
    packed = pack_project(store, project["id"], tmp_path / "move.ilt.zip")
    image.unlink()
    other = ProjectStore(tmp_path / "machine-b")
    loaded = unpack_project(other, packed.path)
    source = Path(loaded.project["pages"][0]["source_path"])
    assert source.is_file()
    assert Image.open(source).getpixel((0, 0)) == (11, 22, 33)


def test_package_omits_secret_marker(tmp_path):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image)
    store.add_sources(project["id"], [image])
    marker = b"ILT_SECRET_MARKER"
    (Path(store.root) / "llm-api-key.txt").write_bytes(marker)
    packed = pack_project(store, project["id"], tmp_path / "pkg.ilt.zip")
    with zipfile.ZipFile(packed.path) as archive:
        for name in archive.namelist():
            assert marker not in archive.read(name)
            assert "llm-api-key" not in name


def test_pack_write_error_keeps_previous_zip(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image, (11, 22, 33))
    store.add_sources(project["id"], [image])
    dest = tmp_path / "pkg.ilt.zip"
    packed = pack_project(store, project["id"], dest)
    previous = packed.path.read_bytes()
    original_write = zipfile.ZipFile.write

    def failing_write(self, filename, arcname=None, *args, **kwargs):
        if str(arcname or "").startswith("pages/"):
            raise OSError("диск заполнен")
        return original_write(self, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", failing_write)
    with pytest.raises(PortableProjectError, match="pages/"):
        pack_project(store, project["id"], dest)
    assert dest.read_bytes() == previous
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
        assert "project.json" in names
        assert any(name.startswith("pages/") for name in names)
