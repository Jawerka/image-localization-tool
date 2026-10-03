"""Экспорт страниц: rename, skip, overwrite, clean и защита оригинала."""

import io
import json
import zipfile

from PIL import Image

from src.app.export import export_archive, export_pages
from src.app.store import ProjectStore


def _page(tmp_path, *, with_clean: bool = False):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    folder = tmp_path / "in"
    source = folder / "page.png"
    source.parent.mkdir()
    Image.new("RGB", (30, 20), (1, 2, 3)).save(source)
    page = store.add_sources(project["id"], [source])[0]
    store.save_image(
        project["id"],
        page["id"],
        "result",
        Image.new("RGB", (12, 10), (9, 9, 9)),
    )
    if with_clean:
        store.save_image(
            project["id"],
            page["id"],
            "clean",
            Image.new("RGB", (12, 10), (40, 40, 40)),
        )
    return store, project, page, source


def test_export_rename_skip_overwrite_and_missing(tmp_path):
    store, project, page, source = _page(tmp_path)
    before = source.read_bytes()
    dest = tmp_path / "out"
    dest.mkdir()
    existing = dest / "page.png"
    existing.write_bytes(b"old")

    renamed, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "rename",
    )
    assert errors == []
    assert renamed == [dest / "page-2.png"]
    assert existing.read_bytes() == b"old"
    assert source.read_bytes() == before

    skipped, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "skip",
    )
    assert skipped == []
    assert errors == []
    assert existing.read_bytes() == b"old"

    written, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "overwrite",
    )
    assert errors == []
    assert written == [dest / "page.png"]
    assert source.read_bytes() == before
    with Image.open(dest / "page.png") as image:
        assert image.size == (12, 10)

    missing, errors = export_pages(
        store, project["id"], ["deadbeef"], dest, "png", 90, "rename",
    )
    assert missing == []
    assert errors

    bare = ProjectStore(tmp_path / "other")
    other = bare.create_project("Пусто", "en", "ru")
    other_image = tmp_path / "empty.png"
    Image.new("RGB", (8, 8), "white").save(other_image)
    other_page = bare.add_sources(other["id"], [other_image])[0]
    paths, errors = export_pages(
        bare, other["id"], [other_page["id"]], dest, "jpg", 80, "rename",
    )
    assert paths == []
    assert errors


def test_export_does_not_overwrite_original(tmp_path):
    store, project, page, source = _page(tmp_path)
    before = source.read_bytes()
    written, errors = export_pages(
        store, project["id"], [page["id"]], source.parent, "png", 90, "overwrite",
    )
    assert errors == []
    assert written == [source.parent / "page-2.png"]
    assert source.read_bytes() == before
    assert (source.parent / "page-2.png").is_file()


def test_export_clean_and_both(tmp_path):
    store, project, page, _source = _page(tmp_path, with_clean=True)
    dest = tmp_path / "out"
    dest.mkdir()

    clean_paths, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "rename", content="clean",
    )
    assert errors == []
    assert clean_paths == [dest / "page.png"]
    with Image.open(dest / "page.png") as image:
        assert image.getpixel((0, 0)) == (40, 40, 40)

    both = tmp_path / "both"
    both.mkdir()
    both_paths, errors = export_pages(
        store, project["id"], [page["id"]], both, "png", 90, "rename", content="both",
    )
    assert errors == []
    assert both_paths == [both / "page.png", both / "page-clean.png"]
    with Image.open(both / "page.png") as image:
        assert image.getpixel((0, 0)) == (9, 9, 9)
    with Image.open(both / "page-clean.png") as image:
        assert image.getpixel((0, 0)) == (40, 40, 40)


def test_export_clean_missing(tmp_path):
    store, project, page, _source = _page(tmp_path, with_clean=False)
    dest = tmp_path / "out"
    dest.mkdir()
    paths, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "rename", content="clean",
    )
    assert paths == []
    assert any("clean.png" in item for item in errors)

    both_paths, both_errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "rename", content="both",
    )
    assert both_paths == []
    assert any("clean.png" in item for item in both_errors)

    # Неизвестное content ведёт себя как перевод.
    fallback, errors = export_pages(
        store, project["id"], [page["id"]], dest, "png", 90, "rename", content="weird",
    )
    assert errors == []
    assert fallback == [dest / "page.png"]


def _patch_pages(store, project_id, fields_by_id):
    """Дописать поля в project.json. Хранилище само chapter/status страницы не ставит."""
    path = store.project_file(project_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    for page in data["pages"]:
        extra = fields_by_id.get(str(page.get("id") or ""))
        if extra:
            page.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_pages(tmp_path, colors_by_name):
    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Глава", "en", "ru")
    folder = tmp_path / "in"
    folder.mkdir(parents=True, exist_ok=True)
    sources = []
    for name in colors_by_name:
        source = folder / name
        Image.new("RGB", (30, 20), (1, 2, 3)).save(source)
        sources.append(source)
    pages = store.add_sources(project["id"], sources)
    by_name = {page["name"]: page for page in pages}
    for name, color in colors_by_name.items():
        page = by_name[name]
        store.save_image(
            project["id"],
            page["id"],
            "result",
            Image.new("RGB", (12, 10), color),
        )
    return store, project, by_name


def _zip_pixel(data: bytes):
    with Image.open(io.BytesIO(data)) as image:
        rgb = image.convert("RGB")
        return rgb.size, rgb.getpixel((0, 0))


def test_export_archive_cbz_members(tmp_path):
    """CBZ без суффикса у dest: глава, пустая глава, ZIP_STORED."""
    store, project, by_name = _make_pages(tmp_path, {
        "page.png": (9, 1, 1),
        "tail.png": (1, 9, 1),
        "nested.png": (1, 1, 9),
    })
    first = by_name["page.png"]
    second = by_name["tail.png"]
    third = by_name["nested.png"]
    # У второй страницы ключа chapter нет — старая запись.
    _patch_pages(store, project["id"], {
        first["id"]: {"chapter": "ch1"},
        third["id"]: {"chapter": "vol/inner"},
    })

    dest = tmp_path / "out" / "chapter"
    result = export_archive(
        store, project["id"], [first["id"], second["id"], third["id"]], dest,
    )
    assert result.errors == []
    assert result.skipped == []
    assert result.paths == [tmp_path / "out" / "chapter.cbz"]
    with zipfile.ZipFile(result.paths[0]) as zf:
        assert zf.namelist() == [
            "ch1/001_page.png",
            "002_tail.png",
            "vol/inner/003_nested.png",
        ]
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert not info.filename.startswith("/")
            assert ".." not in info.filename.split("/")
        assert _zip_pixel(zf.read("ch1/001_page.png")) == ((12, 10), (9, 1, 1))
        assert _zip_pixel(zf.read("002_tail.png")) == ((12, 10), (1, 9, 1))
        assert _zip_pixel(zf.read("vol/inner/003_nested.png")) == ((12, 10), (1, 1, 9))


def test_export_archive_only_ready(tmp_path):
    """only_ready пишет done и ready; idle, error и пустой статус — «не готова»."""
    store, project, by_name = _make_pages(tmp_path, {
        "idle.png": (9, 9, 9),
        "err.png": (9, 9, 9),
        "blank.png": (9, 9, 9),
        "done.png": (2, 3, 4),
        "ready.png": (5, 6, 7),
    })
    idle = by_name["idle.png"]
    err = by_name["err.png"]
    blank = by_name["blank.png"]
    done = by_name["done.png"]
    ready = by_name["ready.png"]
    store.update_status(project["id"], err["id"], status="error")
    store.update_status(project["id"], blank["id"], status="done")
    store.update_status(project["id"], done["id"], status="done")
    # Пустой status в записи проекта важнее done в page.json.
    # ready в хранилище записать нельзя — только в JSON проекта.
    _patch_pages(store, project["id"], {
        blank["id"]: {"status": ""},
        ready["id"]: {"status": "ready"},
    })

    dest = tmp_path / "book.cbz"
    result = export_archive(
        store,
        project["id"],
        [idle["id"], err["id"], blank["id"], done["id"], ready["id"]],
        dest,
        only_ready=True,
    )
    assert result.errors == []
    assert result.paths == [dest]
    assert result.skipped == [
        {"id": idle["id"], "name": "idle.png", "reason": "не готова"},
        {"id": err["id"], "name": "err.png", "reason": "не готова"},
        {"id": blank["id"], "name": "blank.png", "reason": "не готова"},
    ]
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["001_done.png", "002_ready.png"]
        assert _zip_pixel(zf.read("001_done.png")) == ((12, 10), (2, 3, 4))
        assert _zip_pixel(zf.read("002_ready.png")) == ((12, 10), (5, 6, 7))
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED


def test_export_archive_zip_suffix_and_skips(tmp_path):
    store, project, page, _source = _page(tmp_path)
    packed = export_archive(
        store, project["id"], [page["id"]], tmp_path / "pack", archive="zip", fmt="jpg",
    )
    assert packed.errors == []
    assert packed.skipped == []
    assert packed.paths == [tmp_path / "pack.zip"]
    with zipfile.ZipFile(packed.paths[0]) as zf:
        assert zf.namelist() == ["001_page.jpg"]
        assert zf.getinfo("001_page.jpg").compress_type == zipfile.ZIP_STORED
        assert _zip_pixel(zf.read("001_page.jpg"))[0] == (12, 10)

    renamed = export_archive(
        store, project["id"], [page["id"]], tmp_path / "book.cbz", archive="zip",
    )
    assert renamed.paths == [tmp_path / "book.zip"]
    assert not (tmp_path / "book.cbz").exists()

    kept = tmp_path / "keep.cbz"
    kept.write_bytes(b"old")
    skipped = export_archive(
        store, project["id"], [page["id"]], kept, only_ready=True,
    )
    assert skipped.paths == []
    assert skipped.errors == []
    assert skipped.skipped == [{
        "id": page["id"], "name": "page.png", "reason": "не готова",
    }]
    assert kept.read_bytes() == b"old"
    assert not (tmp_path / "none.cbz").exists()
    empty = export_archive(store, project["id"], [], tmp_path / "none.cbz")
    assert empty.paths == []
    assert empty.skipped == []
    assert not (tmp_path / "none.cbz").exists()

    gap_file = tmp_path / "in" / "gap.png"
    Image.new("RGB", (8, 8), "white").save(gap_file)
    gap = store.add_sources(project["id"], [gap_file])[0]
    mixed = export_archive(
        store, project["id"], [gap["id"], page["id"]], tmp_path / "mix.cbz",
    )
    assert mixed.paths == [tmp_path / "mix.cbz"]
    assert mixed.skipped == [{
        "id": gap["id"], "name": "gap.png", "reason": "нет result.png",
    }]
    assert mixed.errors == ["gap.png: нет result.png"]
    with zipfile.ZipFile(mixed.paths[0]) as zf:
        assert zf.namelist() == ["001_page.png"]

    unknown = export_archive(
        store, project["id"], ["deadbeef"], tmp_path / "no.cbz",
    )
    assert unknown.paths == []
    assert not (tmp_path / "no.cbz").exists()
    assert unknown.skipped == [{
        "id": "deadbeef", "name": "deadbeef", "reason": "страница не найдена",
    }]
    assert unknown.errors == ["deadbeef: страница не найдена"]


def test_export_archive_both_and_clean(tmp_path):
    store, project, page, _source = _page(tmp_path, with_clean=True)
    _patch_pages(store, project["id"], {page["id"]: {"chapter": "vol1"}})
    dest = tmp_path / "both.cbz"
    result = export_archive(
        store, project["id"], [page["id"]], dest, content="both",
    )
    assert result.errors == []
    assert result.skipped == []
    assert result.paths == [dest]
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["vol1/001_page.png", "vol1/001_page-clean.png"]
        assert _zip_pixel(zf.read("vol1/001_page.png")) == ((12, 10), (9, 9, 9))
        assert _zip_pixel(zf.read("vol1/001_page-clean.png")) == ((12, 10), (40, 40, 40))

    clean = export_archive(
        store, project["id"], [page["id"]], tmp_path / "clean.cbz", content="clean",
    )
    assert clean.errors == []
    with zipfile.ZipFile(clean.paths[0]) as zf:
        assert zf.namelist() == ["vol1/001_page.png"]
        assert _zip_pixel(zf.read("vol1/001_page.png")) == ((12, 10), (40, 40, 40))

    gap_file = tmp_path / "in" / "gap.png"
    Image.new("RGB", (8, 8), "white").save(gap_file)
    gap = store.add_sources(project["id"], [gap_file])[0]
    store.save_image(
        project["id"], gap["id"], "result", Image.new("RGB", (8, 8), (3, 3, 3)),
    )
    missing = export_archive(
        store, project["id"], [gap["id"]], tmp_path / "noclean.cbz", content="both",
    )
    assert missing.paths == []
    assert not (tmp_path / "noclean.cbz").exists()
    assert missing.skipped == [{
        "id": gap["id"], "name": "gap.png", "reason": "нет clean.png",
    }]
    assert missing.errors == ["gap.png: нет clean.png"]


def test_export_archive_strips_unsafe_segments(tmp_path):
    store, project, page, _source = _page(tmp_path)
    _patch_pages(store, project["id"], {page["id"]: {"chapter": "ch1/../secret"}})
    nested = export_archive(
        store,
        project["id"],
        [page["id"]],
        tmp_path / "safe.cbz",
        name_template="{chapter}/../{index:03}_{stem}",
    )
    with zipfile.ZipFile(nested.paths[0]) as zf:
        assert zf.namelist() == ["ch1/secret/001_page.png"]

    rooted = export_archive(
        store,
        project["id"],
        [page["id"]],
        tmp_path / "slash.cbz",
        name_template="/{index:03}_{stem}",
    )
    with zipfile.ZipFile(rooted.paths[0]) as zf:
        assert zf.namelist() == ["001_page.png"]

    drive = export_archive(
        store,
        project["id"],
        [page["id"]],
        tmp_path / "drive.cbz",
        name_template="C:/{index:03}_{stem}",
    )
    with zipfile.ZipFile(drive.paths[0]) as zf:
        assert zf.namelist() == ["001_page.png"]
