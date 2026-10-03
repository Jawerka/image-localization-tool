"""Очередь заданий на фейковом воркере, без моделей и процессов."""

import json

from PIL import Image

from src.app.events import WorkerEvent
from src.app.jobs import Job, JobQueue, compute_needs_llm, skip_ready
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.watchdog import wait_for_parent
from src.app.worker import FakeWorker, ProcessWorker, RestartPolicy


def test_needs_llm_snapshot_and_events():
    worker = FakeWorker()
    queue = JobQueue(worker)
    online = AppSettings(llm_base_url="http://127.0.0.1:9/v1")
    translate = queue.submit("translate_page", "project1", "page", settings=online)
    online.llm_base_url = "http://changed/v1"
    assert translate.needs_llm is True
    assert translate.settings["llm_base_url"] == "http://127.0.0.1:9/v1"
    assert "api_key" not in translate.settings

    offline = AppSettings(
        llm_base_url="http://127.0.0.1:9/v1",
        ocr_backend="rapid",
        translator_backend="argos",
    )
    assert queue.submit("translate_page", "project1", "page", settings=offline).needs_llm is False
    assert queue.submit("translate_page", "project1", "page", settings=AppSettings()).needs_llm is False
    assert compute_needs_llm("translate_page", {
        "llm_base_url": "http://127.0.0.1:9/v1",
        "ocr_backend": "rapid",
        "translator_backend": "llm",
    }) is True
    assert queue.submit("recognize", "project1", "page", settings=AppSettings()).needs_llm is True
    edit = queue.submit(
        "apply_document",
        "project1",
        "page",
        settings=online,
        payload={"plan": "typeset"},
    )
    assert edit.needs_llm is False
    assert queue.submit("export", "project1", settings=online).needs_llm is False

    events = queue.drain_events()
    assert any(event.type == "job.finished" for event in events)
    assert any(event.type == "page.updated" and event.payload.get("plan") == "typeset" for event in events)
    assert events[0].to_dict()["type"] == events[0].type
    assert queue.drain_events() == []


def test_translate_and_edit_with_store(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    image_path = tmp_path / "page.png"
    Image.new("RGB", (32, 16), "white").save(image_path)
    page = store.add_sources(project["id"], [image_path])[0]
    worker = FakeWorker()
    queue = JobQueue(worker)
    queue.submit(
        "translate_page",
        project["id"],
        page["id"],
        settings=AppSettings(llm_base_url="http://127.0.0.1:9/v1"),
        payload={"store_root": str(tmp_path), "source_path": str(image_path)},
    )
    queue.submit(
        "apply_document",
        project["id"],
        page["id"],
        settings=AppSettings(),
        payload={"plan": "clean"},
    )
    events = queue.drain_events()
    kinds = [event.type for event in events]
    assert "job.started" in kinds
    assert "job.progress" in kinds
    assert "page.updated" in kinds
    assert "job.finished" in kinds
    assert any(event.payload.get("plan") == "clean" for event in events if event.type == "page.updated")
    document = store.read_document(project["id"], page["id"])
    assert document.regions[0].translation == "Привет"
    assert store.read_auto(project["id"], page["id"]).regions[0].text == "Hello"
    with Image.open(store.image_path(project["id"], page["id"], "result")) as result:
        assert result.size == (8, 8)
    assert store.page_status(project["id"], page["id"])["status"] == "done"


def test_edit_does_not_wait_for_batch():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    queue.submit("translate_page", "abcd1234", "aaaa1111", settings=settings)
    queue.submit(
        "apply_document",
        "abcd1234",
        "aaaa1111",
        settings=settings,
        payload={"plan": "typeset"},
    )
    assert [job.kind for job in worker.calls] == ["translate_page", "apply_document"]


def test_cancel_drops_unstarted_batch():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    first = queue.submit("translate_page", "abcd1234", "aaaa1111", settings=settings)
    second = queue.submit("translate_page", "abcd1234", "bbbb2222", settings=settings)
    queue.cancel()
    assert queue.cancel_requested is True
    assert worker.cancel_calls == [None]
    assert [job.id for job in worker.calls] == [first.id]
    cancelled = [
        event.payload["job_id"]
        for event in queue.drain_events()
        if event.type == "job.cancelled"
    ]
    assert second.id in cancelled
    assert queue.drain_events() == []


def test_restart_policy_window():
    policy = RestartPolicy()
    assert policy.allow(0) is True
    assert policy.allow(10) is True
    assert policy.allow(20) is True
    assert policy.allow(30) is False
    assert policy.allow(61) is True


def test_process_worker_is_not_started():
    worker = ProcessWorker()
    assert worker._process is None
    assert worker.on_page_done is None
    worker.cancel()
    worker.shutdown()
    assert worker._process is None


def test_fake_worker_page_hook_skips_pipeline():
    """Хук видит remote_job_id и не запускает настоящий пайплайн."""
    seen = []
    worker = FakeWorker()
    assert worker.on_page_done is None

    def hook(job, event):
        seen.append((job.kind, event.type, job.payload.get("remote_job_id"), job.payload.get("skip_ready")))

    worker.on_page_done = hook
    queue = JobQueue(worker)
    queue.submit(
        "translate_page",
        "project1",
        "page",
        settings=AppSettings(),
        payload={"remote_job_id": "remote-1", "skip_ready": False},
    )
    assert seen == [("translate_page", "job.finished", "remote-1", False)]
    assert worker.on_page_done is hook


def test_watchdog_imports():
    assert callable(wait_for_parent)


def test_synchronous_finish_releases_batch_slot():
    worker = FakeWorker()
    queue = JobQueue(worker)
    first = queue.submit("translate_page", "project1", "p1", settings=AppSettings())
    second = queue.submit("translate_page", "project1", "p2", settings=AppSettings())
    assert [job.id for job in worker.calls] == [first.id, second.id]
    assert queue.job_status(first.id) == "done"
    assert queue.job_status(second.id) == "done"


def test_pause_holds_next_batch_until_resume():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    first = queue.submit("translate_page", "proj", "p1", settings=settings)
    queue.pause()
    second = queue.submit("translate_page", "proj", "p2", settings=settings)
    assert queue.paused is True
    assert queue.job_status(first.id) == "running"
    assert queue.job_status(second.id) == "queued"
    assert [job.id for job in worker.calls] == [first.id]
    queue.push_event(WorkerEvent("job.finished", {"job_id": first.id}))
    assert queue.job_status(first.id) == "done"
    assert queue.job_status(second.id) == "queued"
    assert [job.id for job in worker.calls] == [first.id]
    queue.resume()
    assert queue.paused is False
    assert [job.id for job in worker.calls] == [first.id, second.id]
    assert queue.job_status(second.id) == "running"


def test_resume_while_batch_inflight_does_not_start_second():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    first = queue.submit("translate_page", "proj", "p1", settings=settings)
    queue.pause()
    second = queue.submit("translate_page", "proj", "p2", settings=settings)
    queue.resume()
    assert [job.id for job in worker.calls] == [first.id]
    assert queue.job_status(second.id) == "queued"
    queue.push_event(WorkerEvent("job.finished", {"job_id": first.id}))
    assert [job.id for job in worker.calls] == [first.id, second.id]
    assert queue.job_status(second.id) == "running"


def test_pause_before_submit():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    queue.pause()
    job = queue.submit("translate_page", "proj", "p1", settings=AppSettings())
    assert worker.calls == []
    assert queue.job_status(job.id) == "queued"
    assert queue.snapshot()["batch"][0]["id"] == job.id
    queue.resume()
    assert [item.id for item in worker.calls] == [job.id]
    assert queue.job_status(job.id) == "running"


def test_resume_sends_paused_edit_ahead_of_next_batch():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    batch = queue.submit("translate_page", "abcd1234", "aaaa1111", settings=settings)
    queue.pause()
    edit = queue.submit(
        "apply_document",
        "abcd1234",
        "aaaa1111",
        settings=settings,
        payload={"plan": "typeset"},
    )
    nxt = queue.submit("translate_page", "abcd1234", "bbbb2222", settings=settings)
    assert [job.id for job in worker.calls] == [batch.id]
    queue.resume()
    assert [job.id for job in worker.calls] == [batch.id, edit.id]
    assert queue.job_status(nxt.id) == "queued"
    assert queue.job_status(edit.id) == "running"


def test_cancel_while_paused_drops_unstarted():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    queue.pause()
    job = queue.submit("translate_page", "proj", "p1", settings=AppSettings())
    queue.cancel()
    assert worker.calls == []
    assert queue.job_status(job.id) == "cancelled"
    assert queue.snapshot()["batch"] == []
    cancelled = [
        event.payload["job_id"]
        for event in queue.drain_events()
        if event.type == "job.cancelled"
    ]
    assert cancelled == [job.id]
    queue.resume()
    assert worker.calls == []


def test_cancel_clears_paused_queue(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    running = queue.submit("translate_page", "proj", "p1", settings=settings)
    queue.pause()
    waiting = queue.submit("translate_page", "proj", "p2", settings=settings)
    edit = queue.submit(
        "apply_document",
        "proj",
        "p1",
        settings=settings,
        payload={"plan": "typeset"},
    )
    queue.cancel()
    assert queue.paused is False
    assert queue.snapshot()["batch"] == []
    assert queue.snapshot()["edits"] == []
    assert worker.cancel_calls == [None]
    assert [job.id for job in worker.calls] == [running.id]
    cancelled = {
        event.payload["job_id"]
        for event in queue.drain_events()
        if event.type == "job.cancelled"
    }
    assert cancelled == {running.id, waiting.id, edit.id}
    path = tmp_path / "queue.json"
    queue.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["paused"] is False
    assert raw["batch"] == []
    assert raw["edits"] == []
    assert raw["running"] == []
    queue.resume()
    assert [job.id for job in worker.calls] == [running.id]


def test_cancel_inflight_marks_cancelled():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    job = queue.submit("translate_page", "proj", "p1", settings=AppSettings())
    queue.cancel(job.id)
    assert queue.job_status(job.id) == "cancelled"
    assert worker.cancel_calls == [job.id]


def test_save_load_round_trip_while_paused(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    queue.pause()
    settings = AppSettings(llm_base_url="http://127.0.0.1:9/v1")
    job = queue.submit(
        "translate_page",
        "proj",
        "page1",
        settings=settings,
        payload={"skip_ready": True, "note": "абв"},
    )
    assert worker.calls == []
    path = tmp_path / "queue.json"
    queue.save(path)
    raw_text = path.read_text(encoding="utf-8")
    assert "абв" in raw_text
    raw = json.loads(raw_text)
    assert raw["paused"] is True
    assert raw["batch"][0]["status"] == "queued"
    assert raw["batch"][0]["job"]["id"] == job.id
    assert raw["edits"] == []
    assert raw["running"] == []
    worker2 = FakeWorker(synchronous=False)
    restored = JobQueue(worker2)
    restored.load(path)
    assert worker2.calls == []
    assert restored.paused is True
    loaded = restored.snapshot()["batch"][0]
    assert loaded["id"] == job.id
    assert loaded["kind"] == job.kind
    assert loaded["project_id"] == job.project_id
    assert loaded["page_id"] == job.page_id
    assert loaded["settings"] == job.settings
    assert loaded["payload"] == job.payload
    assert loaded["needs_llm"] == job.needs_llm
    assert "api_key" not in loaded["settings"]
    assert restored.job_status(job.id) == "queued"
    assert skip_ready(Job.from_dict(loaded)) is True
    restored.resume()
    assert [item.id for item in worker2.calls] == [job.id]
    assert worker2.calls[0].payload["skip_ready"] is True


def test_running_job_restored_as_queued_at_front(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    settings = AppSettings()
    first = queue.submit("translate_page", "proj", "p1", settings=settings)
    queue.pause()
    second = queue.submit(
        "translate_page",
        "proj",
        "p2",
        settings=settings,
        payload={"skip_ready": False},
    )
    assert queue.job_status(first.id) == "running"
    path = tmp_path / "queue.json"
    queue.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["running"] == [{
        "status": "running",
        "lane": "batch",
        "job": first.to_dict(),
    }]
    assert [item["job"]["id"] for item in raw["batch"]] == [second.id]
    worker2 = FakeWorker(synchronous=False)
    restored = JobQueue(worker2)
    restored.load(path)
    assert worker2.calls == []
    assert restored.paused is True
    assert restored.job_status(first.id) == "queued"
    assert restored.job_status(second.id) == "queued"
    assert [item["id"] for item in restored.snapshot()["batch"]] == [first.id, second.id]
    restored.resume()
    assert [item.id for item in worker2.calls] == [first.id]
    assert restored.job_status(second.id) == "queued"


def test_load_missing_file_is_noop(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    queue.pause()
    job = queue.submit("translate_page", "proj", "p1", settings=AppSettings())
    queue.load(tmp_path / "missing.json")
    assert queue.paused is True
    assert queue.job_status(job.id) == "queued"
    assert worker.calls == []


def test_load_unpaused_does_not_autostart(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    queue.pause()
    job = queue.submit(
        "translate_page",
        "proj",
        "p1",
        settings=AppSettings(),
        payload={"skip_ready": True},
    )
    path = tmp_path / "queue.json"
    queue.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["paused"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    worker2 = FakeWorker(synchronous=False)
    restored = JobQueue(worker2)
    restored.load(path)
    assert restored.paused is False
    assert worker2.calls == []
    assert restored.job_status(job.id) == "queued"
    restored.resume()
    assert [item.id for item in worker2.calls] == [job.id]


def test_retry_failed_submits_when_not_paused():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    job = queue.submit("translate_page", "proj", "p1", settings=AppSettings())
    queue.push_event(WorkerEvent("job.failed", {"job_id": job.id, "error": "x"}))
    assert queue.job_status(job.id) == "error"
    assert len(worker.calls) == 1
    retried = queue.retry_failed()
    assert retried == [job]
    assert retried[0] is job
    assert queue.job_status(job.id) == "running"
    assert [item.id for item in worker.calls] == [job.id, job.id]
    assert queue.retry_failed() == []


def test_retry_failed_while_paused_stays_queued():
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    job = queue.submit("apply_document", "proj", "p1", settings=AppSettings(), payload={"plan": "x"})
    queue.push_event(WorkerEvent("job.failed", {"job_id": job.id, "error": "x"}))
    queue.pause()
    retried = queue.retry_failed()
    assert [item.id for item in retried] == [job.id]
    assert queue.job_status(job.id) == "queued"
    assert len(worker.calls) == 1
    assert [item["id"] for item in queue.snapshot()["edits"]] == [job.id]
    assert queue.retry_failed() == []
    assert [item["id"] for item in queue.snapshot()["edits"]] == [job.id]


def test_error_survives_save_load_then_retry(tmp_path):
    worker = FakeWorker(synchronous=False)
    queue = JobQueue(worker)
    job = queue.submit(
        "translate_page",
        "proj",
        "p1",
        settings=AppSettings(),
        payload={"skip_ready": True},
    )
    queue.push_event(WorkerEvent("job.failed", {"job_id": job.id, "error": "x"}))
    path = tmp_path / "queue.json"
    queue.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["history"][0]["status"] == "error"
    assert raw["history"][0]["job"]["id"] == job.id
    assert raw["history"][0]["job"]["payload"]["skip_ready"] is True
    assert raw["batch"] == []
    assert raw["running"] == []
    worker2 = FakeWorker(synchronous=False)
    restored = JobQueue(worker2)
    restored.load(path)
    assert worker2.calls == []
    assert restored.job_status(job.id) == "error"
    assert restored.snapshot()["batch"] == []
    retried = restored.retry_failed()
    assert [item.id for item in retried] == [job.id]
    assert len(worker2.calls) == 1
    assert worker2.calls[0].payload["skip_ready"] is True
    assert restored.job_status(job.id) == "running"
    assert restored.retry_failed() == []


def test_skip_ready_reads_payload():
    assert skip_ready(Job("a", "translate_page", "p", payload={"skip_ready": True})) is True
    assert skip_ready(Job("b", "translate_page", "p", payload={"skip_ready": False})) is False
    assert skip_ready(Job("c", "translate_page", "p")) is False
    assert skip_ready(Job("d", "translate_page", "p", payload={"other": True})) is False


def test_skip_ready_does_not_overwrite_result(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    image_path = tmp_path / "page.png"
    Image.new("RGB", (16, 16), "white").save(image_path)
    page = store.add_sources(project["id"], [image_path])[0]
    store.save_image(project["id"], page["id"], "result", Image.new("RGB", (4, 4), (200, 10, 10)))
    worker = FakeWorker()
    queue = JobQueue(worker)
    queue.submit(
        "translate_page",
        project["id"],
        page["id"],
        payload={"store_root": str(tmp_path), "skip_ready": True},
    )
    with Image.open(store.image_path(project["id"], page["id"], "result")) as result:
        assert result.size == (4, 4)
        assert result.getpixel((0, 0)) == (200, 10, 10)
    assert store.page_status(project["id"], page["id"])["status"] == "idle"


def test_pause_tells_worker_to_hold_the_lane():
    class Gate:
        def __init__(self):
            self.paused = 0
            self.resumed = 0
            self.calls = []

        def submit(self, job):
            self.calls.append(job)

        def pause(self):
            self.paused += 1

        def resume(self):
            self.resumed += 1

    worker = Gate()
    queue = JobQueue(worker)
    queue.pause()
    queue.submit("translate_page", "project", "page")
    assert worker.paused == 1
    assert worker.calls == []
    queue.resume()
    assert worker.resumed == 1
    assert [job.kind for job in worker.calls] == ["translate_page"]


def test_lane_does_not_start_while_paused():
    import queue as queue_mod
    import threading

    from src.app.worker import _Runtime

    ctx = _Runtime(queue_mod.Queue())
    ctx.pause_lane()
    started: list[str] = []

    def wait() -> None:
        assert ctx.wait_to_start() is True
        started.append("go")

    thread = threading.Thread(target=wait)
    thread.start()
    thread.join(0.3)
    assert thread.is_alive()
    assert started == []
    ctx.resume_lane()
    thread.join(1)
    assert started == ["go"]


def test_queue_file_unfinished(tmp_path):
    from src.app.worker import queue_has_unfinished

    path = tmp_path / "queue.json"
    assert queue_has_unfinished(path) is False
    path.write_text('{"paused": false, "batch": [], "edits": [], "running": []}\n', encoding="utf-8")
    assert queue_has_unfinished(path) is False
    path.write_text(
        '{"batch": [{"status": "queued", "job": {"id": "a"}}], "edits": [], "running": []}\n',
        encoding="utf-8",
    )
    assert queue_has_unfinished(path) is True


def test_import_path_chapters_and_archive(tmp_path):
    import io
    import json
    import zipfile

    store = ProjectStore(tmp_path / "data")
    project = store.create_project("Книга", "en", "ru")
    root = tmp_path / "book"
    (root / "ch1").mkdir(parents=True)
    (root / "ch2").mkdir()
    Image.new("RGB", (8, 8), "white").save(root / "page10.png")
    Image.new("RGB", (8, 8), "white").save(root / "ch1" / "page2.png")
    Image.new("RGB", (8, 8), "white").save(root / "ch2" / "page3.png")
    Image.new("RGB", (8, 8), "white").save(root / "ch1" / "cover-mask.png")

    added = store.import_path(project["id"], root, recursive=True, chapter_mode="subdir")
    assert [(item["chapter"], item["name"]) for item in added] == [
        ("ch1", "page2.png"),
        ("ch2", "page3.png"),
        ("", "page10.png"),
    ]
    assert store.add_sources(project["id"], [root / "page10.png"], chapter="лишняя") == []

    saved = json.loads(store.project_file(project["id"]).read_text(encoding="utf-8"))
    saved["pages"][0].pop("chapter")
    store.project_file(project["id"]).write_text(
        json.dumps(saved, ensure_ascii=False),
        encoding="utf-8",
    )
    assert store.open_project(project["id"])["pages"][0]["chapter"] == ""

    flat = store.create_project("Плоско", "en", "ru")
    flat_added = store.import_path(flat["id"], root, recursive=True, chapter_mode="flat")
    assert {item["chapter"] for item in flat_added} == {""}

    archive = tmp_path / "pack.cbz"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in ("page10.png", "page2.png"):
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
            bundle.writestr(name, buffer.getvalue())
    packed = store.import_path(project["id"], archive, chapter_mode="subdir")
    assert [item["name"] for item in packed] == ["page2.png", "page10.png"]
    assert {item["chapter"] for item in packed} == {"pack"}
