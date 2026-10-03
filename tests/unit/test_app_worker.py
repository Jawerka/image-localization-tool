"""Вёрстка не затирает более новую правку."""

import threading

from PIL import Image

from src.app import worker
from src.app.document import PageDocument
from src.app.store import ProjectStore
from src.models import TextRegion


def test_stale_typeset_is_dropped(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page = store.add_sources(project["id"], [source])[0]
    page_id = page["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [
        TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="новое"),
    ]
    store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    stale = PageDocument.from_dict(store.read_document(project["id"], page_id).to_dict())
    stale.regions[0].translation = "старое"

    class _Pipe:
        def typeset_image(self, image, regions, lang, warnings, progress_callback=None, cancel_check=None):
            if progress_callback:
                progress_callback(40, "typeset", "typeset")
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    class _Ctx:
        typeset_lock = threading.Lock()
        events = []

        def cancel_check(self, _job_id):
            return lambda: False

        def emit(self, event):
            self.events.append(event)

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    ctx = _Ctx()
    job = {
        "id": "job-1",
        "project_id": project["id"],
        "page_id": page_id,
        "settings": {},
        "payload": {},
    }
    worker._paint(
        job,
        ctx,
        store,
        stale,
        "typeset",
        page_id,
        str(source),
        image=None,
        snapshot=False,
        base_version=1,
    )

    kept = store.read_document(project["id"], page_id)
    assert kept.version == 2
    assert kept.regions[0].translation == "новое"
    assert not store.image_path(project["id"], page_id, "result").is_file()
    assert store.page_status(project["id"], page_id)["status"] == "edited"
    assert [event.type for event in ctx.events] == ["job.progress"]
