"""Хранилище проектов: сортировка, миниатюры, версии."""

from PIL import Image

from src.app.document import PageDocument
from src.app.store import ProjectStore, VersionConflict, natural_key
from src.models import TextRegion


def _png(path, size=(320, 100), color=(20, 40, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_natural_key_page2_before_page10():
    assert natural_key("page2") < natural_key("page10")
    names = ["page10.png", "page2.png", "page1.png"]
    assert sorted(names, key=natural_key) == ["page1.png", "page2.png", "page10.png"]


def test_add_sources_thumb_duplicate_and_remove(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    folder = tmp_path / "chapter"
    _png(folder / "page10.png", (320, 100))
    _png(folder / "page2.png", (320, 80))
    _png(folder / "cover-mask.png", (20, 20))
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    nested = folder / "nested"
    _png(nested / "page3.png")

    added = store.add_sources(project["id"], [folder])
    assert [item["name"] for item in added] == ["page2.png", "page10.png"]
    page2 = added[0]
    with Image.open(store.image_path(project["id"], page2["id"], "thumb")) as thumb:
        assert thumb.size[0] == 160
    assert store.page_status(project["id"], page2["id"])["status"] == "idle"

    source = folder / "page2.png"
    before = source.read_bytes()
    assert store.add_sources(project["id"], [source]) == []
    assert len(store.open_project(project["id"])["pages"]) == 2

    store.remove_pages(project["id"], [page2["id"]])
    assert source.read_bytes() == before
    assert not store.page_dir(project["id"], page2["id"]).exists()
    assert [item["name"] for item in store.open_project(project["id"])["pages"]] == ["page10.png"]


def test_version_conflict_and_auto_snapshot(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    _png(image, (40, 20))
    page = store.add_sources(project["id"], [image])[0]
    document = store.read_document(project["id"], page["id"])
    assert document.version == 1
    document.regions = [
        TextRegion(id=1, bbox=(0, 0, 4, 4), text="a", translation="б"),
    ]
    saved = store.write_document(project["id"], page["id"], document, base_version=1)
    assert saved.version == 2

    saved.regions[0].translation = "другой"
    try:
        store.write_document(project["id"], page["id"], saved, base_version=1)
        raised = False
    except VersionConflict as exc:
        raised = True
        assert exc.document.version == 2
    assert raised
    assert store.read_document(project["id"], page["id"]).regions[0].translation == "б"

    saved.regions[0].translation = "третий"
    final = store.write_document(project["id"], page["id"], saved, base_version=2)
    assert final.version == 3
    assert store.read_document(project["id"], page["id"]).regions[0].translation == "третий"

    auto = PageDocument(regions=[TextRegion(id=2, bbox=(1, 1, 2, 2), text="auto")])
    store.write_auto(project["id"], page["id"], auto)
    assert store.read_auto(project["id"], page["id"]).regions[0].text == "auto"

    picture = Image.new("RGB", (6, 6), "white")
    store.save_image(project["id"], page["id"], "result", picture)
    assert store.image_path(project["id"], page["id"], "result").is_file()
