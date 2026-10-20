"""Вёрстка не затирает более новую правку."""

import queue
import sys
import threading
import time
import types

import pytest
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
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None, cancel_check=None, incremental=None):
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


def test_retranslation_does_not_replace_newer_user_input(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page = store.add_sources(project["id"], [source])[0]
    page_id = page["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="старый перевод")]
    store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    class _Pipe:
        translator = types.SimpleNamespace(warnings=[])
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def retranslate_region(self, image, regions, region_id, source_lang, target_lang,
                               cancel_check=None):
            latest = store.read_document(project["id"], page_id)
            latest.regions[0].translation = "свежий ручной ввод"
            store.write_document(project["id"], page_id, latest, base_version=latest.version)
            regions[0].translation = "устаревший ответ"

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None, cancel_check=None, incremental=None):
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    class _Ctx:
        llm_lock = threading.Lock()
        typeset_lock = threading.Lock()
        lama_lock = threading.Lock()
        events = []

        def cancel_check(self, _job_id):
            return lambda: False

        def emit(self, event):
            self.events.append(event)

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    context = _Ctx()
    worker._run_region({
        "id": "job-retranslate",
        "kind": "retranslate",
        "project_id": project["id"],
        "page_id": page_id,
        "payload": {"region_id": 1, "base_version": 1, "store_root": str(store.root)},
    }, context)

    saved = store.read_document(project["id"], page_id)
    assert saved.regions[0].translation == "свежий ручной ввод"
    assert not store.image_path(project["id"], page_id, "result").is_file()
    assert [event.type for event in context.events] == ["page.updated"]


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
        typesetter = types.SimpleNamespace(_last_region_bounds={1: (0, 0, 0, 0)})

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None, cancel_check=None, incremental=None):
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


def test_paint_uses_current_provenance_and_refreshes_it(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "incremental.png"
    Image.new("RGB", (60, 40), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    previous = store.read_document(project["id"], page_id)
    previous.regions = [TextRegion(id=1, bbox=(2, 2, 45, 30), text="Hi", translation="Старый")]
    previous = store.write_document(project["id"], page_id, previous, base_version=1)
    clean = Image.new("RGB", (60, 40), "white")
    store.save_image(project["id"], page_id, "clean", clean)
    store.save_image(project["id"], page_id, "result", clean)
    store.record_result_provenance(
        project["id"], page_id, document_version=previous.version,
        region_bounds={1: (2, 2, 20, 14)},
    )
    current = PageDocument.from_dict(previous.to_dict())
    current.regions[0].translation = "Новый"
    store.write_document(project["id"], page_id, current, base_version=previous.version)

    seen = {}

    class _Pipe:
        typesetter = types.SimpleNamespace(_last_region_bounds={1: (2, 2, 18, 14)})

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None,
                          cancel_check=None, incremental=None):
            seen["incremental"] = incremental
            return Image.new("RGB", image.size, (250, 250, 250)), []

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
    context = _Ctx()
    worker._paint(
        {"id": "incremental", "project_id": project["id"], "page_id": page_id,
         "settings": {}, "payload": {"previous_document": previous.to_dict(), "changed_region_ids": [1]}},
        context, store, current, "typeset", page_id, str(source), image=None,
        snapshot=False, base_version=previous.version + 1,
    )
    assert seen["incremental"]["changed_region_ids"] == [1]
    assert seen["incremental"]["previous_bounds"] == {"1": [2, 2, 20, 14]}
    updated = store.read_result_provenance(project["id"], page_id)
    assert updated["document_version"] == current.version
    assert updated["region_bounds"] == {"1": [2, 2, 18, 14]}


def test_paint_accepts_nonvisual_bump_during_render(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="старое")]
    document = store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))
    store.save_image(project["id"], page_id, "result", Image.new("RGB", (40, 20), "white"))
    store.record_result_provenance(
        project["id"], page_id, document_version=document.version, region_bounds={},
    )
    store.update_status(project["id"], page_id, status="done")

    rendered_document = PageDocument.from_dict(document.to_dict())
    rendered_document.regions[0].translation = "новое"
    rendered_document = store.write_document(
        project["id"], page_id, rendered_document, base_version=document.version,
    )
    store.mark_visual_version(project["id"], page_id, rendered_document.version)

    class _Pipe:
        typesetter = types.SimpleNamespace(_last_region_bounds={1: (0, 0, 0, 0)})

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None,
                          cancel_check=None, incremental=None):
            latest = store.read_document(project["id"], page_id)
            latest.warnings = ["невизуальная правка"]
            store.write_document(project["id"], page_id, latest, base_version=latest.version)
            return Image.new("RGB", image.size, (0, 200, 0)), []

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
    worker._paint(
        {
            "id": "paint-nonvisual",
            "project_id": project["id"],
            "page_id": page_id,
            "settings": {},
            "payload": {},
        },
        _Ctx(),
        store,
        rendered_document,
        "typeset",
        page_id,
        str(source),
        image=None,
        snapshot=False,
        base_version=rendered_document.version,
    )

    saved = store.read_document(project["id"], page_id)
    assert saved.version == rendered_document.version + 1
    assert saved.warnings == ["невизуальная правка"]
    assert store.read_result_provenance(project["id"], page_id)["document_version"] == saved.version
    assert store.visual_version(project["id"], page_id) == saved.version
    assert store.page_status(project["id"], page_id)["status"] == "done"
    with Image.open(store.image_path(project["id"], page_id, "result")) as image:
        assert image.getpixel((0, 0)) == (0, 200, 0)


def test_paint_keeps_bounds_of_its_own_render(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    pages = {}
    sources = {}
    for name, text in (("a", "A"), ("b", "B")):
        source = tmp_path / f"{name}.png"
        Image.new("RGB", (40, 20), "white").save(source)
        page_id = store.add_sources(project["id"], [source])[0]["id"]
        document = store.read_document(project["id"], page_id)
        document.regions = [
            TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation=text),
        ]
        document = store.write_document(
            project["id"], page_id, document, base_version=document.version,
        )
        store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))
        store.save_image(project["id"], page_id, "result", Image.new("RGB", (40, 20), "white"))
        store.record_result_provenance(
            project["id"], page_id, document_version=document.version, region_bounds={},
        )
        store.update_status(project["id"], page_id, status="done")
        pages[text] = (page_id, document)
        sources[text] = source

    class _Pipe:
        def __init__(self):
            self.typesetter = types.SimpleNamespace(_last_region_bounds={})

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None,
                          cancel_check=None, incremental=None):
            self.typesetter._last_region_bounds = (
                {1: (1, 1, 5, 5)}
                if regions[0].translation == "A"
                else {1: (10, 10, 20, 20)}
            )
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    pipe = _Pipe()
    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (pipe, _Config()))
    original_commit = worker._commit_fresh
    a_rendered = threading.Event()
    release_a = threading.Event()

    def commit(store_, job, document, page_id, *, snapshot, base_version):
        if page_id == pages["A"][0]:
            a_rendered.set()
            assert release_a.wait(2)
        return original_commit(
            store_, job, document, page_id,
            snapshot=snapshot, base_version=base_version,
        )

    monkeypatch.setattr(worker, "_commit_fresh", commit)
    context = worker._Runtime(queue.Queue())
    job_a = {
        "id": "paint-a",
        "project_id": project["id"],
        "page_id": pages["A"][0],
        "settings": {},
        "payload": {},
    }
    thread = threading.Thread(
        target=worker._paint,
        args=(
            job_a, context, store, pages["A"][1], "typeset",
            pages["A"][0], str(sources["A"]),
        ),
        kwargs={"image": None, "snapshot": False, "base_version": pages["A"][1].version},
        daemon=True,
    )
    thread.start()
    assert a_rendered.wait(2)
    worker._paint(
        {
            "id": "paint-b",
            "project_id": project["id"],
            "page_id": pages["B"][0],
            "settings": {},
            "payload": {},
        },
        context,
        store,
        pages["B"][1],
        "typeset",
        pages["B"][0],
        str(sources["B"]),
        image=None,
        snapshot=False,
        base_version=pages["B"][1].version,
    )
    release_a.set()
    thread.join(2)

    assert store.read_result_provenance(
        project["id"], pages["A"][0]
    )["region_bounds"] == {"1": [1, 1, 5, 5]}
    assert store.read_result_provenance(
        project["id"], pages["B"][0]
    )["region_bounds"] == {"1": [10, 10, 20, 20]}


def test_region_without_visual_change_restores_done(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="Привет")]
    document = store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))
    store.update_status(project["id"], page_id, status="done")

    class _Pipe:
        translator = types.SimpleNamespace(warnings=[])

        def shorten_region(self, region, target_lang, cancel_check=None):
            return None

    class _Config:
        target_lang = "ru"

    class _Ctx:
        llm_lock = threading.Lock()
        events = []

        def cancel_check(self, _job_id):
            return lambda: False

        def emit(self, event):
            self.events.append(event)

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    context = _Ctx()
    worker._run_region({
        "id": "shorten-1",
        "kind": "shorten",
        "project_id": project["id"],
        "page_id": page_id,
        "payload": {
            "region_id": 1,
            "base_version": document.version,
            "previous_status": "done",
            "store_root": str(store.root),
        },
    }, context)

    assert store.page_status(project["id"], page_id)["status"] == "done"
    assert store.read_document(project["id"], page_id).version == document.version + 1
    assert [event.type for event in context.events] == ["page.updated"]


def test_cancel_keeps_flag_while_job_is_held():
    import queue as queue_mod

    ctx = worker._Runtime(queue_mod.Queue())
    ctx.hold("batch", {"id": "job1", "kind": "translate_page"})
    worker._cancel_lanes(ctx, queue_mod.Queue(), queue_mod.Queue(), queue_mod.Queue(), None)
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
    worker._cancel_lanes(ctx, work, queue_mod.Queue(), queue_mod.Queue(), None)
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


class _StubPipe:
    """Минимальный пайплайн для проверки сброса клиентов в ``_pipeline``."""

    def __init__(self, config=None):
        self.config = config
        self.ocr = None
        self.translator = None
        self.ocr_name = ""
        self.translator_name = ""
        self.inpainter = object()
        self._llm_down = False
        self._shared_client = None
        self.typesetter = types.SimpleNamespace(
            min_font_size=10,
            max_font_size=128,
            stroke_ratio=0.08,
            margin_ratio=0.08,
            lang="ru",
        )


def test_pipeline_recreates_clients_when_key_changes(monkeypatch):
    from src.app.settings import set_api_key

    assert set_api_key("first-key")
    module = types.ModuleType("src.page_pipeline")
    module.PagePipeline = _StubPipe
    monkeypatch.setitem(sys.modules, "src.page_pipeline", module)

    ctx = worker._Runtime(queue.Queue())
    settings = {"llm_base_url": "http://box/v1"}
    pipe, _ = worker._pipeline(ctx, settings, reset_clients=True)
    pipe.ocr = object()
    pipe.translator = object()
    pipe._shared_client = object()
    pipe._llm_down = True

    same, _ = worker._pipeline(ctx, settings, reset_clients=True)
    assert same is pipe
    assert same.ocr is not None
    assert same.translator is not None
    assert same._shared_client is not None

    assert set_api_key("second-key")
    changed, _ = worker._pipeline(ctx, settings, reset_clients=True)
    assert changed is pipe
    assert changed.ocr is None
    assert changed.translator is None
    assert changed._shared_client is None
    assert changed._llm_down is False
    assert changed.inpainter is not None


def _export_page(tmp_path, *, status="running", provenance_version=1):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (24, 16), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    image = Image.new("RGB", (24, 16), "white")
    store.save_image(project["id"], page_id, "clean", image)
    store.save_image(project["id"], page_id, "result", image)
    store.record_result_provenance(
        project["id"],
        page_id,
        document_version=provenance_version,
        region_bounds={},
    )
    store.update_status(project["id"], page_id, status=status)
    return store, project["id"], page_id


def test_export_wait_waits_for_newer_result(tmp_path):
    store, project_id, page_id = _export_page(tmp_path)
    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "payload": {
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 2},
        },
    }

    def finish():
        time.sleep(0.1)
        store.update_status(project_id, page_id, status="done")
        store.record_result_provenance(
            project_id, page_id, document_version=2, region_bounds={},
        )

    thread = threading.Thread(target=finish, daemon=True)
    thread.start()
    started = time.monotonic()
    worker._wait_export_ready(
        store, job, worker._Runtime(queue.Queue()), timeout=2,
    )
    thread.join(1)
    assert time.monotonic() - started >= 0.05
    assert store.read_result_provenance(project_id, page_id)["document_version"] == 2


def test_export_wait_reports_error_page_immediately(tmp_path):
    store, project_id, page_id = _export_page(tmp_path)
    store.update_status(project_id, page_id, status="error", error="нет модели")
    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "payload": {
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 2},
        },
    }
    with pytest.raises(RuntimeError, match="нет модели"):
        worker._wait_export_ready(
            store, job, worker._Runtime(queue.Queue()), timeout=2,
        )


def test_export_wait_times_out_instead_of_exporting_stale(tmp_path):
    store, project_id, page_id = _export_page(tmp_path)
    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "payload": {
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 2},
        },
    }
    with pytest.raises(RuntimeError, match="Результат ещё готовится"):
        worker._wait_export_ready(
            store, job, worker._Runtime(queue.Queue()), timeout=0.15,
        )


def test_export_wait_allows_legacy_result_only_when_done(tmp_path):
    store, project_id, page_id = _export_page(tmp_path, provenance_version=1)
    store.save_image(
        project_id, page_id, "result", Image.new("RGB", (24, 16), "white"),
    )
    store.update_status(project_id, page_id, status="done")
    assert store.read_result_provenance(project_id, page_id) is None
    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "payload": {
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 99},
        },
    }
    worker._wait_export_ready(
        store, job, worker._Runtime(queue.Queue()), timeout=0.2,
    )


def test_export_copies_new_result_after_wait(tmp_path):
    store, project_id, page_id = _export_page(tmp_path)
    dest = tmp_path / "out"
    fresh = Image.new("RGB", (24, 16), (10, 200, 10))

    def finish():
        time.sleep(0.1)
        store.save_image(project_id, page_id, "result", fresh)
        store.record_result_provenance(
            project_id, page_id, document_version=2, region_bounds={},
        )
        store.update_status(project_id, page_id, status="done")

    thread = threading.Thread(target=finish, daemon=True)
    thread.start()
    result = worker._run_export({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 2},
        },
    }, worker._Runtime(queue.Queue()))
    thread.join(1)
    assert result["saved"] == 1
    with Image.open(dest / "page.png") as image:
        assert image.getpixel((0, 0)) == (10, 200, 10)


def test_export_lane_waits_without_blocking_edits(tmp_path, monkeypatch):
    store, project_id, page_id = _export_page(tmp_path)
    dest = tmp_path / "out"
    ctx = worker._Runtime(queue.Queue())
    edit_queue = queue.Queue()
    export_queue = queue.Queue()
    applied = threading.Event()

    def dispatch(job, runtime):
        if job["kind"] == "export":
            worker._run_export(job, runtime)
            return
        time.sleep(0.05)
        store.update_status(project_id, page_id, status="done")
        store.record_result_provenance(
            project_id, page_id, document_version=2, region_bounds={},
        )
        applied.set()

    monkeypatch.setattr(worker, "_dispatch", dispatch)
    threads = [
        threading.Thread(target=worker._lane_loop, args=("edit", edit_queue, ctx), daemon=True),
        threading.Thread(
            target=worker._lane_loop, args=("export", export_queue, ctx), daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    export_queue.put({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {page_id: 2},
        },
    })
    edit_queue.put({
        "id": "edit-1",
        "kind": "apply_document",
        "project_id": project_id,
        "page_id": page_id,
        "payload": {},
    })
    assert applied.wait(2)
    deadline = time.monotonic() + 2
    exported = dest / "page.png"
    while time.monotonic() < deadline and not exported.is_file():
        time.sleep(0.02)
    assert exported.is_file()
    for lane in (edit_queue, export_queue):
        lane.put(None)
    for thread in threads:
        thread.join(1)


def test_export_does_not_copy_when_cancelled_before_lock(tmp_path):
    from src.errors import PipelineCancelled

    store, project_id, page_id = _export_page(tmp_path, status="done")
    dest = tmp_path / "out"
    ctx = worker._Runtime(queue.Queue())
    ctx.cancelled_ids.add("export-1")
    ctx.cancel_event.set()
    with pytest.raises(PipelineCancelled):
        worker._run_export({
            "id": "export-1",
            "kind": "export",
            "project_id": project_id,
            "page_id": "",
            "payload": {
                "store_root": str(store.root),
                "dest": str(dest),
                "page_ids": [page_id],
                "content": "result",
                "required_document_versions": {page_id: 1},
            },
        }, ctx)
    assert not (dest / "page.png").exists()


def test_export_failure_does_not_touch_other_lane_page(tmp_path):
    store, project_id, page_id = _export_page(tmp_path)
    ctx = worker._Runtime(queue.Queue())
    ctx.page_id = page_id
    worker._dispatch({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {"store_root": str(store.root)},
    }, ctx)
    assert store.page_status(project_id, page_id)["status"] == "running"


def test_export_wait_accepts_nonvisual_document_bump(tmp_path):
    store, project_id, page_id = _export_page(tmp_path, status="done")
    document = store.read_document(project_id, page_id)
    document.warnings = ["только предупреждение"]
    base = document.version
    store.write_document(project_id, page_id, document, base_version=base)
    assert store.read_document(project_id, page_id).version == base + 1
    assert store.visual_version(project_id, page_id) == base
    worker._wait_export_ready(store, {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "payload": {
            "page_ids": [page_id],
            "content": "result",
            "required_document_versions": {
                page_id: store.visual_version(project_id, page_id),
            },
        },
    }, worker._Runtime(queue.Queue()), timeout=0.2)


def test_export_rechecks_state_under_lock(tmp_path, monkeypatch):
    store, project_id, page_id = _export_page(tmp_path, status="done")
    old = Image.new("RGB", (24, 16), (200, 0, 0))
    store.save_image(project_id, page_id, "clean", old)
    store.save_image(project_id, page_id, "result", old)
    store.record_result_provenance(
        project_id, page_id, document_version=1, region_bounds={},
    )
    dest = tmp_path / "out"
    blue = Image.new("RGB", (24, 16), (0, 0, 200))
    green = Image.new("RGB", (24, 16), (0, 200, 0))
    original = worker._wait_export_ready
    calls = 0

    def wrapped(store_, job, ctx, *, timeout, pending_ok=False, blocked=None):
        nonlocal calls
        calls += 1
        ready = original(
            store_, job, ctx,
            timeout=timeout, pending_ok=pending_ok, blocked=blocked,
        )
        if calls == 1:
            store_.save_image(project_id, page_id, "clean", blue)
            store_.update_status(project_id, page_id, status="running")

            def finish():
                time.sleep(0.1)
                store_.save_image(project_id, page_id, "result", green)
                store_.record_result_provenance(
                    project_id, page_id, document_version=1, region_bounds={},
                )
                store_.update_status(project_id, page_id, status="done")

            threading.Thread(target=finish, daemon=True).start()
        return ready

    monkeypatch.setattr(worker, "_wait_export_ready", wrapped)
    worker._run_export({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id],
            "content": "both",
            "required_document_versions": {page_id: 1},
        },
    }, worker._Runtime(queue.Queue()))

    with Image.open(dest / "page.png") as result:
        assert result.getpixel((0, 0)) == (0, 200, 0)
    with Image.open(dest / "page-clean.png") as clean:
        assert clean.getpixel((0, 0)) == (0, 0, 200)


def test_cancel_unknown_job_does_not_wedge_worker():
    ctx = worker._Runtime(queue.Queue())
    worker._cancel_lanes(ctx, queue.Queue(), queue.Queue(), queue.Queue(), "missing")
    assert ctx.cancelled_ids == set()
    assert ctx.cancel_event.is_set() is False
    ctx.hold("edit", {"id": "next", "kind": "apply_document"})
    assert ctx.should_skip("next") is False


def test_restart_does_not_resubmit_cancelled_export():
    proc = worker.ProcessWorker()
    proc._stop_process = lambda: None
    started = []
    proc._start = lambda: started.append(True)
    seen = []
    proc.event_sink = seen.append
    proc._inflight["export"] = {
        "id": "export",
        "kind": "export",
        "project_id": "proj",
        "page_id": "",
        "payload": {},
    }
    proc._restart_stuck(resubmit_edits=True, cancelled_id="export")
    assert started == [True]
    assert [event.type for event in seen if event.type in ("job.cancelled", "job.failed")] == [
        "job.cancelled"
    ]


def test_cancelled_region_does_not_commit_and_restores_status(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [
        TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="Привет"),
    ]
    document = store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))
    store.update_status(project["id"], page_id, status="done")

    events = queue.Queue()
    ctx = worker._Runtime(events)

    class _Pipe:
        translator = types.SimpleNamespace(warnings=[])

        def retranslate_region(
            self, image, regions, region_id, source_lang, target_lang, cancel_check=None,
        ):
            regions[0].translation = "Новый"
            ctx.cancelled_ids.add("region-1")
            ctx.cancel_event.set()
            return regions[0]

    class _Config:
        target_lang = "ru"

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    worker._dispatch({
        "id": "region-1",
        "kind": "retranslate",
        "project_id": project["id"],
        "page_id": page_id,
        "payload": {
            "region_id": 1,
            "previous_status": "done",
            "store_root": str(store.root),
        },
    }, ctx)

    assert store.read_document(project["id"], page_id).version == document.version
    assert store.page_status(project["id"], page_id)["status"] == "done"
    kinds = []
    while True:
        try:
            kinds.append(events.get_nowait()["type"])
        except queue.Empty:
            break
    assert "page.updated" in kinds
    assert "job.cancelled" in kinds


def test_cancelled_apply_does_not_commit(tmp_path, monkeypatch):
    from src.errors import PipelineCancelled

    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [
        TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="Привет"),
    ]
    document = store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    ctx = worker._Runtime(queue.Queue())

    class _Pipe:
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def typeset_image(
            self, image, regions, lang, warnings,
            progress_callback=None, cancel_check=None, incremental=None,
        ):
            ctx.cancelled_ids.add("apply-1")
            ctx.cancel_event.set()
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    with pytest.raises(PipelineCancelled):
        worker._paint(
            {
                "id": "apply-1",
                "kind": "apply_document",
                "project_id": project["id"],
                "page_id": page_id,
                "payload": {"store_root": str(store.root)},
            },
            ctx,
            store,
            document,
            "typeset",
            page_id,
            str(source),
            image=None,
            snapshot=False,
            base_version=document.version,
        )
    assert store.read_document(project["id"], page_id).version == document.version


def test_batch_translation_keeps_manual_edit_during_analysis(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [
        TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="старое"),
    ]
    store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    class _Pipe:
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def analyze(
            self, image, source_path, source_lang, target_lang,
            progress_callback=None, cancel_check=None,
        ):
            latest = store.read_document(project["id"], page_id)
            latest.regions[0].translation = "ручная правка"
            store.write_document(project["id"], page_id, latest, base_version=latest.version)
            return types.SimpleNamespace(
                regions=[TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="пакет")],
                reading_direction="ltr",
                warnings=[],
                timings={},
                ocr_engine="test",
                translator_engine="test",
            )

        def clean(
            self, image, regions, strokes=None, warnings=None,
            progress_callback=None, cancel_check=None,
        ):
            return Image.new("L", image.size, 0), image.copy()

        def typeset_image(
            self, image, regions, lang, warnings,
            progress_callback=None, cancel_check=None, incremental=None,
        ):
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    worker._translate_page(
        {
            "id": "batch-1",
            "kind": "translate_page",
            "project_id": project["id"],
            "page_id": page_id,
            "settings": {},
            "payload": {"store_root": str(store.root)},
        },
        worker._Runtime(queue.Queue()),
        store,
        {"page_id": page_id, "source_path": str(source)},
    )

    saved = store.read_document(project["id"], page_id)
    assert saved.version == document.version + 1
    assert saved.regions[0].translation == "ручная правка"


def test_batch_without_regions_replaces_stale_clean(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (24, 16), (10, 120, 40)).save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    old = Image.new("RGB", (24, 16), (200, 0, 0))
    store.save_image(project["id"], page_id, "clean", old)
    store.save_image(project["id"], page_id, "result", old)
    store.save_image(project["id"], page_id, "mask", Image.new("L", (24, 16), 255))
    store.record_result_provenance(
        project["id"], page_id, document_version=1, region_bounds={},
    )
    store.update_status(project["id"], page_id, status="done")

    class _Pipe:
        def analyze(self, image, source_path, source_lang, target_lang,
                    progress_callback=None, cancel_check=None):
            return types.SimpleNamespace(
                regions=[],
                reading_direction="ltr",
                warnings=[],
                timings={},
                ocr_engine="test",
                translator_engine="test",
            )

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    worker._translate_page(
        {
            "id": "batch-1",
            "kind": "translate_page",
            "project_id": project["id"],
            "page_id": page_id,
            "settings": {},
            "payload": {"store_root": str(store.root)},
        },
        worker._Runtime(queue.Queue()),
        store,
        {"page_id": page_id, "source_path": str(source)},
    )

    saved = store.read_document(project["id"], page_id)
    assert store.page_status(project["id"], page_id)["status"] == "done"
    provenance = store.read_result_provenance(project["id"], page_id)
    assert provenance is not None
    assert provenance["document_version"] == saved.version
    assert store.clean_provenance_is_current(project["id"], page_id, saved.version)
    for kind in ("clean", "result"):
        with Image.open(store.image_path(project["id"], page_id, kind)) as image:
            assert image.convert("RGB").getpixel((0, 0)) == (10, 120, 40)
    assert not store.image_path(project["id"], page_id, "mask").exists()


def test_cancel_settle_skips_page_busy_in_other_lane(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.update_status(project["id"], page_id, status="running")

    ctx = worker._Runtime(queue.Queue())
    ctx.hold("edit", {
        "id": "region-1",
        "kind": "retranslate",
        "project_id": project["id"],
        "page_id": page_id,
        "payload": {"store_root": str(store.root)},
    })
    worker._report_stuck_pages(
        {
            "id": "batch-1",
            "kind": "translate_all",
            "project_id": project["id"],
            "page_id": "",
            "payload": {
                "store_root": str(store.root),
                "pages": [{"page_id": page_id}],
            },
        },
        ctx,
        error="",
        fail_current=False,
    )
    assert store.page_status(project["id"], page_id)["status"] == "running"


def test_export_partial_result_is_finished_not_failed(tmp_path):
    store, project_id, page_id = _export_page(tmp_path, status="done")
    missing = tmp_path / "missing.png"
    Image.new("RGB", (24, 16), "white").save(missing)
    missing_id = store.add_sources(project_id, [missing])[0]["id"]
    dest = tmp_path / "out"

    result = worker._run_export({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id, missing_id],
            "content": "result",
        },
    }, worker._Runtime(queue.Queue()))

    assert result["saved"] == 1
    assert result["errors"]
    assert (dest / "page.png").is_file()


def test_export_skips_failed_page_but_saves_ready(tmp_path):
    store, project_id, page_id = _export_page(tmp_path, status="done")
    broken = tmp_path / "broken.png"
    Image.new("RGB", (24, 16), "white").save(broken)
    broken_id = store.add_sources(project_id, [broken])[0]["id"]
    image = Image.new("RGB", (24, 16), "white")
    store.save_image(project_id, broken_id, "clean", image)
    store.save_image(project_id, broken_id, "result", image)
    store.record_result_provenance(
        project_id, broken_id, document_version=1, region_bounds={},
    )
    store.update_status(project_id, broken_id, status="error", error="нет модели")
    dest = tmp_path / "out"

    result = worker._run_export({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id, broken_id],
            "content": "result",
        },
    }, worker._Runtime(queue.Queue()))

    assert result["saved"] == 1
    assert (dest / "page.png").is_file()
    assert not (dest / "broken.png").exists()
    assert any("нет модели" in item for item in result["errors"])


def test_export_skips_page_that_fails_during_wait(tmp_path, monkeypatch):
    store, project_id, page_id = _export_page(tmp_path, status="done")
    later = tmp_path / "later.png"
    Image.new("RGB", (24, 16), "white").save(later)
    later_id = store.add_sources(project_id, [later])[0]["id"]
    image = Image.new("RGB", (24, 16), "white")
    store.save_image(project_id, later_id, "clean", image)
    store.save_image(project_id, later_id, "result", image)
    store.record_result_provenance(
        project_id, later_id, document_version=1, region_bounds={},
    )
    store.update_status(project_id, later_id, status="running")

    original_wait = worker._wait_export_ready

    def wait_after_failure(store_, job, ctx, *, timeout, pending_ok=False, blocked=None):
        # Страница была running при первой проверке и упала до ожидания.
        store_.update_status(project_id, later_id, status="error", error="boom")
        return original_wait(
            store_, job, ctx,
            timeout=timeout, pending_ok=pending_ok, blocked=blocked,
        )

    monkeypatch.setattr(worker, "_wait_export_ready", wait_after_failure)
    dest = tmp_path / "out"
    result = worker._run_export({
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "dest": str(dest),
            "page_ids": [page_id, later_id],
            "content": "result",
        },
    }, worker._Runtime(queue.Queue()))

    assert result["saved"] == 1
    assert (dest / "page.png").is_file()
    assert not (dest / "later.png").exists()
    assert any("boom" in item for item in result["errors"])


def test_cancel_apply_restores_edited(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.update_status(project["id"], page_id, status="running")

    class _Ctx:
        def emit(self, _event):
            return None

        def busy_page_ids(self, _exclude=""):
            return set()

    worker._report_stuck_pages(
        {
            "id": "apply-1",
            "kind": "apply_document",
            "project_id": project["id"],
            "page_id": page_id,
            "payload": {"store_root": str(store.root)},
        },
        _Ctx(),
        error="",
        fail_current=False,
    )
    assert store.page_status(project["id"], page_id)["status"] == "edited"


def test_export_page_ids_are_job_pages():
    assert worker._job_page_ids({
        "id": "export-1",
        "kind": "export",
        "page_id": "",
        "payload": {"page_ids": ["p1", "p2"]},
    }) == ["p1", "p2"]

def test_status_page_ids_exclude_export_and_ready_skip(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 10), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.save_image(project["id"], page_id, "result", Image.new("RGB", (20, 10), "white"))

    export = {"kind": "export", "page_id": "", "payload": {"page_ids": [page_id]}}
    assert worker._status_page_ids(export) == []

    job = {
        "kind": "translate_all",
        "project_id": project["id"],
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "skip_ready": True,
            "pages": [{"page_id": page_id}],
        },
    }
    assert worker._status_page_ids(job) == []
    job["payload"]["skip_ready"] = False
    assert worker._status_page_ids(job) == [page_id]


def test_finish_status_keeps_edited_when_visual_version_is_newer(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 10), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    store.mark_visual_version(project["id"], page_id, 5)

    worker._finish_status(
        store,
        {"project_id": project["id"]},
        document,
        page_id,
        document.version,
    )

    assert store.page_status(project["id"], page_id)["status"] == "edited"


def test_region_without_base_version_does_not_overwrite_newer_save(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="старый")]
    store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))

    class _Pipe:
        translator = types.SimpleNamespace(warnings=[])
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def retranslate_region(self, image, regions, region_id, source_lang, target_lang,
                               cancel_check=None):
            latest = store.read_document(project["id"], page_id)
            latest.regions[0].translation = "свежий ручной ввод"
            store.write_document(project["id"], page_id, latest, base_version=latest.version)
            regions[0].translation = "устаревший ответ"

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None,
                          cancel_check=None, incremental=None):
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    class _Ctx:
        llm_lock = threading.Lock()
        typeset_lock = threading.Lock()
        lama_lock = threading.Lock()
        events = []

        def cancel_check(self, _job_id):
            return lambda: False

        def emit(self, event):
            self.events.append(event)

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    context = _Ctx()
    worker._run_region({
        "id": "job-retranslate",
        "kind": "retranslate",
        "project_id": project["id"],
        "page_id": page_id,
        "payload": {"region_id": 1, "store_root": str(store.root)},
    }, context)

    saved = store.read_document(project["id"], page_id)
    assert saved.regions[0].translation == "свежий ручной ввод"
    assert not store.image_path(project["id"], page_id, "result").is_file()


def test_stale_clean_is_not_published_before_commit(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    document = store.read_document(project["id"], page_id)
    document.regions = [TextRegion(id=1, bbox=(0, 0, 20, 10), text="Hi", translation="новое")]
    store.write_document(project["id"], page_id, document, base_version=1)
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (40, 20), "white"))
    store.update_status(project["id"], page_id, status="running")
    stale = PageDocument.from_dict(store.read_document(project["id"], page_id).to_dict())
    stale.regions[0].translation = "старое"

    class _Pipe:
        typesetter = types.SimpleNamespace(_last_region_bounds={})

        def clean(self, image, regions, strokes=None, warnings=None,
                  progress_callback=None, cancel_check=None):
            return Image.new("L", image.size, 255), Image.new("RGB", image.size, "blue")

        def typeset_image(self, image, regions, lang, warnings, progress_callback=None,
                          cancel_check=None, incremental=None):
            return image, []

    class _Config:
        target_lang = "ru"
        translate_sfx = False

    class _Ctx:
        lama_lock = threading.Lock()
        typeset_lock = threading.Lock()
        events = []

        def cancel_check(self, _job_id):
            return lambda: False

        def emit(self, event):
            self.events.append(event)

    monkeypatch.setattr(worker, "_pipeline", lambda *_args, **_kwargs: (_Pipe(), _Config()))
    worker._paint(
        {"id": "job-1", "project_id": project["id"], "page_id": page_id,
         "settings": {}, "payload": {}},
        _Ctx(), store, stale, "clean", page_id, str(source),
        image=None, snapshot=False, base_version=1,
    )

    with Image.open(store.image_path(project["id"], page_id, "clean")) as clean:
        assert clean.getpixel((0, 0)) == (255, 255, 255)
    assert not store.image_path(project["id"], page_id, "result").is_file()
    assert store.page_status(project["id"], page_id)["status"] == "edited"


def test_export_wait_rejects_clean_rewritten_after_provenance(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (24, 16), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.save_image(project["id"], page_id, "clean", Image.new("RGB", (24, 16), "white"))
    store.save_image(project["id"], page_id, "result", Image.new("RGB", (24, 16), "white"))
    store.record_result_provenance(
        project["id"], page_id, document_version=1, region_bounds={},
    )
    store.update_status(project["id"], page_id, status="done")
    store.image_path(project["id"], page_id, "clean").write_bytes(b"stale")

    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project["id"],
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "page_ids": [page_id],
            "content": "clean",
            "required_document_versions": {page_id: 1},
        },
    }
    assert worker._wait_export_ready(
        store, job, worker._Runtime(queue.Queue()), timeout=0, pending_ok=True,
    ) is False


def test_export_wait_only_ready_keeps_offline_page(tmp_path):
    store, project_id, page_id = _export_page(tmp_path, status="offline")
    store.image_path(project_id, page_id, "clean").write_bytes(b"stale")
    job = {
        "id": "export-1",
        "kind": "export",
        "project_id": project_id,
        "page_id": "",
        "payload": {
            "store_root": str(store.root),
            "page_ids": [page_id],
            "archive": "cbz",
            "only_ready": True,
            "content": "clean",
            "required_document_versions": {page_id: 1},
        },
    }
    assert worker._wait_export_ready(
        store, job, worker._Runtime(queue.Queue()), timeout=0, pending_ok=True,
    ) is False


def test_report_stuck_pages_skips_page_busy_in_other_lane(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 10), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.update_status(project["id"], page_id, status="running")

    class _Ctx:
        def emit(self, _event):
            return None

        def busy_page_ids(self, _exclude=""):
            return {page_id}

    worker._report_stuck_pages(
        {
            "id": "apply-1",
            "kind": "apply_document",
            "project_id": project["id"],
            "page_id": page_id,
            "payload": {"store_root": str(store.root)},
        },
        _Ctx(),
        error="boom",
        fail_current=True,
    )
    assert store.page_status(project["id"], page_id)["status"] == "running"


def test_restart_limit_closes_stuck_pages(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 10), "white").save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.update_status(project["id"], page_id, status="running")

    events = []
    process = worker.ProcessWorker(event_sink=events.append)
    process.policy = worker.RestartPolicy(max_restarts=0)
    item = {
        "id": "apply-1",
        "kind": "apply_document",
        "project_id": project["id"],
        "page_id": page_id,
        "settings": {},
        "payload": {"store_root": str(store.root)},
    }
    process._inflight = {item["id"]: item}
    monkeypatch.setattr(process, "_stop_process", lambda: None)

    process._restart_stuck(resubmit_edits=True)

    assert store.page_status(project["id"], page_id)["status"] == "error"
    assert any(event.type == "job.failed" for event in events)
