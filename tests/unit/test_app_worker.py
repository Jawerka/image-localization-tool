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
    updated = [event for event in ctx.events if event.type == "page.updated"]
    assert [event.type for event in ctx.events] == ["job.progress", "page.updated"]
    assert updated[0].payload["status"] == "edited"


def test_paint_reports_done(tmp_path, monkeypatch):
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
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    class _Pipe:
        def typeset_image(self, image, regions, lang, warnings, progress_callback=None, cancel_check=None):
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
        "id": "job-2",
        "project_id": project["id"],
        "page_id": page_id,
        "settings": {},
        "payload": {},
    }
    worker._paint(
        job,
        ctx,
        store,
        document,
        "typeset",
        page_id,
        str(source),
        image=None,
        snapshot=False,
        base_version=None,
    )

    updated = [event for event in ctx.events if event.type == "page.updated"]
    assert len(updated) == 1
    assert updated[0].payload["status"] == "done"
    assert updated[0].payload["progress"] == 100
    assert store.page_status(project["id"], page_id)["status"] == "done"


def test_cancel_keeps_flag_while_job_is_held():
    import queue as queue_mod

    ctx = worker._Runtime(queue_mod.Queue())
    ctx.hold("batch", {"id": "job1", "kind": "translate_page"})
    worker._cancel_lanes(ctx, queue_mod.Queue(), queue_mod.Queue(), None)
    assert ctx.cancel_all is True
    assert ctx.should_skip("job1") is True


def test_held_job_is_cancelled_without_starting():
    import queue as queue_mod
    import time

    events = queue_mod.Queue()
    ctx = worker._Runtime(events)
    ctx.pause_lane()
    work = queue_mod.Queue()
    work.put({"id": "job1", "kind": "no-such", "page_id": "p", "project_id": "proj", "payload": {}})
    thread = threading.Thread(target=worker._lane_loop, args=("batch", work, ctx), daemon=True)
    thread.start()
    for _ in range(40):
        if ctx.held["batch"]:
            break
        time.sleep(0.02)
    assert ctx.held["batch"]
    worker._cancel_lanes(ctx, work, queue_mod.Queue(), None)
    seen = []
    deadline = time.time() + 2
    while time.time() < deadline and "job.cancelled" not in seen:
        try:
            raw = events.get(timeout=0.1)
        except queue_mod.Empty:
            continue
        seen.append(raw.get("type"))
    work.put(None)
    thread.join(1)
    assert "job.cancelled" in seen
    assert "job.started" not in seen
    assert "job.failed" not in seen


def test_batch_failure_idles_queued_tail(tmp_path):
    import queue as queue_mod

    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    Image.new("RGB", (8, 8), "white").save(first)
    Image.new("RGB", (8, 8), "white").save(second)
    pages = store.add_sources(project["id"], [first, second])
    store.update_status(project["id"], pages[0]["id"], status="running")
    store.update_status(project["id"], pages[1]["id"], status="queued")
    ctx = worker._Runtime(queue_mod.Queue())
    ctx.page_id = pages[0]["id"]
    worker._dispatch({
        "id": "job",
        "kind": "no-such",
        "project_id": project["id"],
        "page_id": "",
        "payload": {
            "store_root": str(tmp_path),
            "pages": [{"page_id": pages[0]["id"]}, {"page_id": pages[1]["id"]}],
        },
    }, ctx)
    assert store.page_status(project["id"], pages[0]["id"])["status"] == "error"
    assert store.page_status(project["id"], pages[1]["id"])["status"] == "idle"


def test_dead_worker_fails_inflight_and_clears_queue_tail(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    Image.new("RGB", (8, 8), "white").save(first)
    Image.new("RGB", (8, 8), "white").save(second)
    pages = store.add_sources(project["id"], [first, second])
    store.update_status(project["id"], pages[0]["id"], status="running")
    store.update_status(project["id"], pages[1]["id"], status="queued")
    proc = worker.ProcessWorker()
    seen = []
    proc.event_sink = seen.append
    proc._inflight["job"] = {
        "id": "job",
        "kind": "translate_all",
        "project_id": project["id"],
        "page_id": "",
        "payload": {
            "store_root": str(tmp_path),
            "pages": [{"page_id": pages[0]["id"]}, {"page_id": pages[1]["id"]}],
        },
    }
    proc._abandon_inflight("Процесс воркера завершился")
    assert proc._inflight == {}
    assert store.page_status(project["id"], pages[0]["id"])["status"] == "error"
    assert store.page_status(project["id"], pages[1]["id"])["status"] == "idle"
    assert any(event.type == "job.failed" for event in seen)


def test_full_stop_does_not_resubmit_edits():
    proc = worker.ProcessWorker()
    proc._stop_process = lambda: None
    started = []
    proc._start = lambda: started.append(True)
    seen = []
    proc.event_sink = seen.append
    proc._inflight["edit"] = {
        "id": "edit",
        "kind": "apply_document",
        "project_id": "proj",
        "page_id": "page",
        "payload": {},
    }
    proc._restart_stuck(resubmit_edits=False)
    assert proc._inflight == {}
    assert started == [True]
    assert [event.type for event in seen if event.type in ("job.cancelled", "job.failed")] == ["job.cancelled"]


def test_restore_turns_running_page_into_queued(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "a.png"
    Image.new("RGB", (8, 8), "white").save(image)
    page = store.add_sources(project["id"], [image])[0]
    store.update_status(project["id"], page["id"], status="running", stage="ocr")
    worker.demote_restored_running(store, [{
        "project_id": project["id"],
        "page_id": page["id"],
        "payload": {},
    }])
    status = store.page_status(project["id"], page["id"])
    assert status["status"] == "queued"
    assert status["stage"] == ""
