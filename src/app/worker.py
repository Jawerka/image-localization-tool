"""Процесс-воркер и фейковый воркер для тестов.

Импорт модуля не загружает PagePipeline и torch: пайплайн создаётся лениво
внутри ``worker_main``. Тесты не должны вызывать ``ProcessWorker.submit``.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

from PIL import Image

from src.app.document import PageDocument
from src.app.events import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_FINISHED,
    JOB_PROGRESS,
    JOB_STARTED,
    PAGE_UPDATED,
    WORKER_FAILED,
    WORKER_RESTARTING,
    WorkerEvent,
)
from src.app.jobs import BATCH_KINDS, Job, skip_ready
from src.app.store import ProjectStore, VersionConflict
from src.errors import PipelineCancelled
from src.models import TextRegion

_TERMINAL = frozenset({JOB_FINISHED, JOB_FAILED, JOB_CANCELLED})
logger = logging.getLogger("ilt.app.worker")


class RestartPolicy:
    """Не больше трёх перезапусков за 60 секунд."""

    def __init__(self, max_restarts: int = 3, window: float = 60.0):
        self.max_restarts = max_restarts
        self.window = window
        self._times: list[float] = []

    def allow(self, now: float) -> bool:
        cutoff = now - self.window
        self._times = [item for item in self._times if item > cutoff]
        if len(self._times) >= self.max_restarts:
            return False
        self._times.append(now)
        return True


class _Runtime:
    """Состояние одного процесса-воркера: отмена, замки и один пайплайн."""

    def __init__(self, event_queue):
        self.event_queue = event_queue
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self.init_lock = threading.Lock()
        self.lama_lock = threading.Lock()
        self.llm_lock = threading.Lock()
        self.typeset_lock = threading.Lock()
        self.cancel_all = False
        self.cancelled_ids: set[str] = set()
        self.running = {"batch": False, "edit": False}
        # Задание уже снято с очереди полосы, но ещё не начато (ждёт паузу).
        self.held = {"batch": None, "edit": None}
        self.pipeline = None
        self.clients_sig = None
        self.page_id = ""
        # Снят — можно брать следующее задание. Пауза его очищает.
        self.run_gate = threading.Event()
        self.run_gate.set()
        self.stop = threading.Event()

    def pause_lane(self) -> None:
        """Не начинать следующее задание. Текущее дорабатывает само."""
        self.run_gate.clear()

    def resume_lane(self) -> None:
        """Снова разрешить брать задания из полосы."""
        self.run_gate.set()

    def request_stop(self) -> None:
        """Разбудить полосу, которая ждёт на паузе, и попросить её выйти."""
        self.stop.set()
        self.run_gate.set()

    def wait_to_start(self) -> bool:
        """Дождаться разрешения начать задание. False — процесс останавливается.

        Отмена снятого, но ещё не начатого задания будит ожидание сразу.
        """
        while not self.run_gate.is_set():
            if self.stop.is_set():
                return False
            if self._held_cancelled():
                return True
            self.run_gate.wait(0.2)
        return not self.stop.is_set()

    def hold(self, lane: str, job: dict) -> None:
        """Запомнить задание, которое полоса уже забрала из очереди."""
        with self.lock:
            self.held[lane] = job

    def _held_cancelled(self) -> bool:
        with self.lock:
            jobs = [job for job in self.held.values() if isinstance(job, dict)]
        return any(self.should_skip(str(job.get("id") or "")) for job in jobs)

    def emit(self, event: WorkerEvent) -> None:
        try:
            self.event_queue.put(event.to_dict())
        except Exception:
            return

    def cancel_check(self, job_id: str):
        def check() -> bool:
            if not self.cancel_event.is_set():
                return False
            with self.lock:
                if self.cancel_all:
                    return True
                return job_id in self.cancelled_ids

        return check

    def should_skip(self, job_id: str) -> bool:
        return self.cancel_check(job_id)()

    def mark_running(self, lane: str) -> None:
        with self.lock:
            self.running[lane] = True

    def finish_job(self, lane: str, job_id: str) -> None:
        with self.lock:
            self.running[lane] = False
            self.held[lane] = None
            self.cancelled_ids.discard(job_id)
            pending = any(self.held.values())
            busy = self.running["batch"] or self.running["edit"] or pending
            if not busy and not self.cancelled_ids:
                self.cancel_all = False
                self.cancel_event.clear()


def _notify_page_done(worker, job, event: WorkerEvent) -> None:
    """Хук завершения страницы. Пока он пустой, пайплайн отсюда не стартует.

    Окно подставляет колбэк, когда есть удалённый сервер: дочерний процесс
    сам ``RemoteServer`` не видит. Сбой хука не роняет полосу.
    """
    hook = getattr(worker, "on_page_done", None)
    if not callable(hook) or job is None:
        return
    try:
        hook(job, event)
    except Exception:
        return


def _notify_progress(worker, job, event: WorkerEvent) -> None:
    """Хук прогресса страницы для удалённого API. Сбой не роняет полосу."""
    hook = getattr(worker, "on_progress", None)
    if not callable(hook) or job is None:
        return
    try:
        hook(job, event)
    except Exception:
        return


def _fake_page_ids(job: Job) -> list[str]:
    """Страницы задания.

    «Перевести страницу» несёт id в самом задании. «Перевести всё» кладёт
    список в payload: у пакетного задания page_id пустой.
    """
    if job.page_id:
        return [str(job.page_id)]
    found: list[str] = []
    raw = job.payload.get("pages")
    if not isinstance(raw, list):
        return found
    for item in raw:
        if not isinstance(item, dict):
            continue
        page_id = str(item.get("page_id") or "")
        if page_id:
            found.append(page_id)
    return found


class FakeWorker:
    """Воркер без моделей: задания выполняются в процессе теста.

    ``synchronous=False`` только принимает задания. Так очередь может снять
    ещё не начатый пакет, пока первое задание числится запущенным.
    """

    def __init__(self, store: ProjectStore | None = None, *, synchronous: bool = True):
        self.store = store
        self.synchronous = synchronous
        self.calls: list[Job] = []
        self.cancel_calls: list[str | None] = []
        self.shutdown_calls = 0
        self.event_sink = None
        # None — тесты не зовут перевод. Окно ставит колбэк для удалённого задания.
        self.on_page_done = None
        self.on_progress = None
        self._holding: list[Job] = []

    def submit(self, job: Job) -> None:
        self.calls.append(job)
        if self.synchronous:
            self._execute(job)
        else:
            self._holding.append(job)

    def cancel(self, job_id: str | None = None) -> None:
        self.cancel_calls.append(job_id)
        if self.synchronous:
            return
        still: list[Job] = []
        for job in self._holding:
            if job_id is None or job.id == job_id:
                cancelled = WorkerEvent(JOB_CANCELLED, _job_ids(job))
                self._emit(cancelled)
                _notify_page_done(self, job, cancelled)
            else:
                still.append(job)
        self._holding = still

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def flush(self) -> None:
        """Выполнить то, что ``synchronous=False`` только принял."""
        pending = list(self._holding)
        self._holding.clear()
        for job in pending:
            self._execute(job)

    def _execute(self, job: Job) -> None:
        self._emit(WorkerEvent(JOB_STARTED, _job_ids(job)))
        finished = _job_ids(job)
        try:
            if job.kind in BATCH_KINDS:
                self._translate(job)
            elif job.kind == "apply_document":
                plan = str(job.payload.get("plan") or "")
                self._emit(WorkerEvent(PAGE_UPDATED, {**_job_ids(job), "plan": plan}))
            elif job.kind == "export":
                # Смоук и юнит-тесты: файл в папку, без процесса пайплайна.
                finished.update(self._export(job))
        except Exception as exc:
            failed = WorkerEvent(JOB_FAILED, {**_job_ids(job), "error": str(exc)})
            self._emit(failed)
            _notify_page_done(self, job, failed)
            return
        finished_event = WorkerEvent(JOB_FINISHED, finished)
        self._emit(finished_event)
        _notify_page_done(self, job, finished_event)

    def _translate(self, job: Job) -> None:
        progress = WorkerEvent(JOB_PROGRESS, {**_job_ids(job), "progress": 50, "stage": "translate"})
        self._emit(progress)
        _notify_progress(self, job, progress)
        page_ids = _fake_page_ids(job)
        store = self._store_of(job)
        wrote = False
        skipped = False
        if store is not None:
            for page_id in page_ids:
                if skip_ready(job) and _result_ready(store, job.project_id, page_id):
                    skipped = True
                    continue
                self._write_fake_page(store, job, page_id)
                wrote = True
                self._emit(WorkerEvent(PAGE_UPDATED, {
                    **_job_ids(job),
                    "page_id": page_id,
                    "plan": "clean",
                    "status": "done",
                    "progress": 100,
                    "stage": "typeset",
                }))
        if not wrote and not skipped:
            self._emit(WorkerEvent(PAGE_UPDATED, {**_job_ids(job), "plan": "clean"}))

    def _store_of(self, job: Job) -> ProjectStore | None:
        if self.store is not None:
            return self.store
        root = job.payload.get("store_root")
        if not root:
            return None
        return ProjectStore(Path(root))

    def _write_fake_page(self, store: ProjectStore, job: Job, page_id: str) -> None:
        """result.png и статус «готово». Размер кадра маленький: модели не нужны."""
        document = PageDocument(
            regions=[
                TextRegion(
                    id=1,
                    bbox=(0, 0, 8, 8),
                    text="Hello",
                    translation="Привет",
                    block_type="dialogue",
                )
            ],
            ocr_engine="fake",
            translator_engine="fake",
        )
        store.write_auto(job.project_id, page_id, document)
        store.write_document(job.project_id, page_id, document, base_version=None)
        store.save_image(
            job.project_id,
            page_id,
            "result",
            Image.new("RGB", (8, 8), "white"),
        )
        store.update_status(
            job.project_id,
            page_id,
            status="done",
            progress=100,
            stage="typeset",
            error="",
        )

    def _export(self, job: Job) -> dict:
        """Скопировать result.png в папку задания. Нет папки — пустой итог."""
        dest = job.payload.get("dest")
        store = self._store_of(job)
        if not dest or store is None or not job.project_id:
            return {}
        archive = str(job.payload.get("archive") or "folder").lower()
        page_ids = [str(item) for item in job.payload.get("page_ids") or []]
        fmt = str(job.payload.get("format") or "png")
        quality = int(job.payload.get("jpeg_quality") or 90)
        content = str(job.payload.get("content") or "result")
        if archive in ("zip", "cbz"):
            from src.app.export import export_archive

            result = export_archive(
                store,
                job.project_id,
                page_ids,
                Path(dest),
                archive=archive,
                fmt=fmt,
                jpeg_quality=quality,
                content=content,
                name_template=str(job.payload.get("name_template") or "{chapter}/{index:03}_{stem}"),
                only_ready=bool(job.payload.get("only_ready")),
            )
        else:
            from src.app.export import export_pages

            result = export_pages(
                store,
                job.project_id,
                page_ids,
                Path(dest),
                fmt,
                quality,
                str(job.payload.get("conflict") or "rename"),
                content=content,
            )
        payload = {
            "paths": [str(path) for path in result.paths],
            "saved": len(result.paths),
            "export": True,
        }
        if result.errors:
            payload["errors"] = list(result.errors)
        skipped = getattr(result, "skipped", None)
        if skipped:
            payload["skipped"] = list(skipped)
        return payload

    def _emit(self, event: WorkerEvent) -> None:
        if self.event_sink is not None:
            self.event_sink(event)


class ProcessWorker:
    """Дочерний процесс со spawn. ``submit`` поднимает его при первом задании."""

    def __init__(self, event_sink=None, policy: RestartPolicy | None = None):
        self.event_sink = event_sink
        self.policy = policy or RestartPolicy()
        self._process = None
        self._commands = None
        self._events = None
        self._listener = None
        self._generation = 0
        self._inflight: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._listener_stop = threading.Event()
        self._lanes_paused = False
        # Колбэки родителя. Дочерний процесс удалённый сервер не видит.
        self.on_page_done = None
        self.on_progress = None

    def pause(self) -> None:
        """Не начинать следующее задание в дочернем процессе."""
        self._lanes_paused = True
        self._send({"cmd": "pause"})

    def resume(self) -> None:
        """Снова разрешить полосам брать задания."""
        self._lanes_paused = False
        self._send({"cmd": "resume"})

    def _send(self, command: dict) -> None:
        commands = self._commands
        if commands is None:
            return
        try:
            commands.put(command)
        except Exception:
            return

    def submit(self, job: Job) -> None:
        if self._closed:
            raise RuntimeError("Воркер остановлен")
        self._ensure()
        payload = job.to_dict()
        with self._lock:
            self._inflight[str(payload.get("id") or "")] = payload
        self._commands.put({"cmd": "submit", "job": payload})

    def cancel(self, job_id: str | None = None) -> None:
        """Отменить задание. Если поток не затих за 3 с — перезапуск процесса."""
        if self._commands is None:
            return
        self._commands.put({"cmd": "cancel", "job_id": job_id})
        if self._wait_idle(3.0, job_id):
            return
        self._restart_stuck(resubmit_edits=job_id is not None)

    def _abandon_inflight(self, error: str) -> None:
        """Процесс умер: закрыть задания и отпустить слот очереди."""
        with self._lock:
            pending = list(self._inflight.values())
            self._inflight.clear()
        for item in pending:
            if not isinstance(item, dict):
                continue
            for page_id in _close_stuck_pages(item, current_id="", error=error, fail_current=False):
                self._emit(WorkerEvent(PAGE_UPDATED, _page_update(_store(item), item, page_id)))
            failed = WorkerEvent(JOB_FAILED, {**_dict_ids(item), "error": error})
            self._emit(failed)
            _notify_page_done(self, item, failed)

    def shutdown(self) -> None:
        self._closed = True
        if self._commands is not None:
            try:
                self._commands.put({"cmd": "shutdown"})
            except Exception:
                pass
        self._stop_process()

    def _ensure(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            return
        self._start()

    def _start(self) -> None:
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        self._commands = context.Queue()
        self._events = context.Queue()
        self._generation += 1
        generation = self._generation
        self._listener_stop.clear()
        process = context.Process(
            target=worker_main,
            args=(self._commands, self._events, os.getpid()),
            name="ilt-worker",
            daemon=True,
        )
        process.start()
        self._process = process
        listener = threading.Thread(
            target=self._listen,
            args=(self._events, generation),
            name="ilt-worker-events",
            daemon=True,
        )
        listener.start()
        self._listener = listener
        if self._lanes_paused:
            self._commands.put({"cmd": "pause"})

    def _listen(self, events, generation: int) -> None:
        while not self._listener_stop.is_set() and generation == self._generation:
            try:
                raw = events.get(timeout=0.2)
            except queue.Empty:
                process = self._process
                if (
                    generation == self._generation
                    and process is not None
                    and not process.is_alive()
                    and not self._closed
                ):
                    self._abandon_inflight("Процесс воркера завершился")
                    self._emit(WorkerEvent(WORKER_FAILED, {"reason": "Процесс воркера завершился"}))
                    return
                continue
            if not isinstance(raw, dict):
                continue
            event = WorkerEvent(type=str(raw.get("type") or ""), payload=dict(raw.get("payload") or {}))
            finished_job = None
            progress_job = None
            job_id = str(event.payload.get("job_id") or "")
            if event.type in _TERMINAL:
                with self._lock:
                    finished_job = self._inflight.pop(job_id, None)
            elif event.type == JOB_PROGRESS and job_id:
                with self._lock:
                    progress_job = self._inflight.get(job_id)
            self._emit(event)
            if progress_job is not None:
                _notify_progress(self, progress_job, event)
            if finished_job is not None:
                _notify_page_done(self, finished_job, event)

    def _wait_idle(self, timeout: float, job_id: str | None) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if job_id is None:
                    busy = bool(self._inflight)
                else:
                    busy = str(job_id) in self._inflight
            process = self._process
            if not busy or process is None or not process.is_alive():
                return True
            time.sleep(0.05)
        return False

    def _restart_stuck(self, *, resubmit_edits: bool = True) -> None:
        with self._lock:
            pending = list(self._inflight.values())
            self._inflight.clear()
        edits = [item for item in pending if item.get("kind") not in BATCH_KINDS]
        batches = [item for item in pending if item.get("kind") in BATCH_KINDS]
        # Полный «Стоп» уже выкинул правки из очереди. Возвращать их нельзя.
        dropped = batches if resubmit_edits else pending
        kept = edits if resubmit_edits else []
        self._stop_process()
        for item in dropped:
            for page_id in _close_stuck_pages(
                item, current_id="", error="", fail_current=False, running_status="idle",
            ):
                self._emit(WorkerEvent(PAGE_UPDATED, _page_update(_store(item), item, page_id)))
            cancelled = WorkerEvent(JOB_CANCELLED, _dict_ids(item))
            self._emit(cancelled)
            _notify_page_done(self, item, cancelled)
        if self._closed:
            return
        if not self.policy.allow(time.time()):
            for item in kept:
                failed = WorkerEvent(
                    JOB_FAILED,
                    {**_dict_ids(item), "error": "Воркер не перезапущен"},
                )
                self._emit(failed)
                _notify_page_done(self, item, failed)
            self._emit(WorkerEvent(WORKER_FAILED, {"reason": "Превышен лимит перезапусков"}))
            return
        self._emit(WorkerEvent(WORKER_RESTARTING, {}))
        self._start()
        for item in kept:
            with self._lock:
                self._inflight[str(item.get("id") or "")] = item
            self._commands.put({"cmd": "submit", "job": item})

    def _stop_process(self) -> None:
        self._generation += 1
        self._listener_stop.set()
        process = self._process
        self._process = None
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=3)

    def _emit(self, event: WorkerEvent) -> None:
        sink = self.event_sink
        if sink is not None:
            sink(event)


def worker_main(command_queue, event_queue, parent_pid: int) -> None:
    """Точка входа дочернего процесса. Два потока: пакет и правки."""
    _redirect_stdio()
    from src.app.watchdog import start_parent_watch

    start_parent_watch(int(parent_pid or 0))
    ctx = _Runtime(event_queue)
    batch_queue: queue.Queue = queue.Queue()
    edit_queue: queue.Queue = queue.Queue()
    threading.Thread(
        target=_lane_loop,
        args=("batch", batch_queue, ctx),
        name="ilt-batch",
        daemon=True,
    ).start()
    threading.Thread(
        target=_lane_loop,
        args=("edit", edit_queue, ctx),
        name="ilt-edits",
        daemon=True,
    ).start()
    while True:
        command = command_queue.get()
        if not isinstance(command, dict):
            continue
        kind = command.get("cmd")
        if kind == "shutdown":
            ctx.request_stop()
            batch_queue.put(None)
            edit_queue.put(None)
            return
        if kind == "pause":
            ctx.pause_lane()
            continue
        if kind == "resume":
            ctx.resume_lane()
            continue
        if kind == "cancel":
            _cancel_lanes(ctx, batch_queue, edit_queue, command.get("job_id"))
            continue
        if kind == "submit":
            job = command.get("job") or {}
            target = batch_queue if job.get("kind") in BATCH_KINDS else edit_queue
            target.put(job)


def _redirect_stdio() -> None:
    """В оконной сборке stdout и stderr равны None — увести их в лог до моделей."""
    import sys

    from src.app.paths import logs_dir
    from src.utils.logger import enable_file_logging

    path = logs_dir() / "worker.log"
    if sys.stdout is None or sys.stderr is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = handle
        if sys.stderr is None:
            sys.stderr = handle
    enable_file_logging(path, rotate=True)


def _lane_loop(lane: str, work_queue: queue.Queue, ctx: _Runtime) -> None:
    while True:
        job = work_queue.get()
        if job is None:
            return
        job_id = str(job.get("id") or "")
        ctx.hold(lane, job)
        try:
            if not ctx.wait_to_start():
                return
            if ctx.should_skip(job_id):
                ctx.emit(WorkerEvent(JOB_CANCELLED, _dict_ids(job)))
                continue
            ctx.mark_running(lane)
            try:
                _dispatch(job, ctx)
            except Exception as exc:
                _log_failure(exc)
                ctx.emit(WorkerEvent(JOB_FAILED, {**_dict_ids(job), "error": str(exc)}))
        finally:
            ctx.finish_job(lane, job_id)


def _cancel_lanes(ctx: _Runtime, batch_queue: queue.Queue, edit_queue: queue.Queue, job_id) -> None:
    selected = None if job_id is None else str(job_id)
    with ctx.lock:
        if selected is None:
            ctx.cancel_all = True
        else:
            ctx.cancelled_ids.add(selected)
        ctx.cancel_event.set()
    removed = _pull_queued(batch_queue, selected)
    removed.extend(_pull_queued(edit_queue, selected))
    for job in removed:
        ctx.cancelled_ids.discard(str(job.get("id") or ""))
        ctx.emit(WorkerEvent(JOB_CANCELLED, _dict_ids(job)))
    with ctx.lock:
        pending = any(ctx.held.values())
        busy = ctx.running["batch"] or ctx.running["edit"] or pending
        if not busy and not ctx.cancelled_ids:
            ctx.cancel_all = False
            ctx.cancel_event.clear()


def _pull_queued(work_queue: queue.Queue, job_id: str | None) -> list[dict]:
    taken: list[dict] = []
    restore = []
    while True:
        try:
            item = work_queue.get_nowait()
        except queue.Empty:
            break
        if item is None:
            restore.append(None)
            break
        if job_id is None or str(item.get("id") or "") == job_id:
            taken.append(item)
        else:
            restore.append(item)
    for item in restore:
        work_queue.put(item)
    return taken


def _dispatch(job: dict, ctx: _Runtime) -> None:
    ctx.page_id = str(job.get("page_id") or "")
    ctx.emit(WorkerEvent(JOB_STARTED, _dict_ids(job)))
    try:
        kind = job.get("kind")
        if kind in BATCH_KINDS:
            _run_translate(job, ctx)
        elif kind == "apply_document":
            _run_apply(job, ctx)
        elif kind in ("recognize", "retranslate", "shorten"):
            _run_region(job, ctx)
        elif kind == "export":
            _run_export(job, ctx)
        else:
            raise RuntimeError(f"Неизвестное задание: {kind}")
    except PipelineCancelled:
        _report_stuck_pages(job, ctx, error="", fail_current=False)
        ctx.emit(WorkerEvent(JOB_CANCELLED, _dict_ids(job, ctx.page_id or None)))
        return
    except Exception as exc:
        _log_failure(exc)
        _report_stuck_pages(job, ctx, error=str(exc), fail_current=True)
        ctx.emit(WorkerEvent(JOB_FAILED, {**_dict_ids(job, ctx.page_id or None), "error": str(exc)}))
        return
    ctx.emit(WorkerEvent(JOB_FINISHED, _dict_ids(job, ctx.page_id or None)))


def _run_translate(job: dict, ctx: _Runtime) -> None:
    store = _store(job)
    payload = job.get("payload") or {}
    project_id = str(job.get("project_id") or "")
    for page in _page_list(job):
        if ctx.cancel_check(str(job.get("id") or ""))():
            raise PipelineCancelled()
        page_id = str(page.get("page_id") or job.get("page_id") or "")
        if payload.get("skip_ready") and _result_ready(store, project_id, page_id):
            continue
        _translate_page(job, ctx, store, page)


def _translate_page(job: dict, ctx: _Runtime, store: ProjectStore, page: dict) -> None:
    page_id = str(page.get("page_id") or job.get("page_id") or "")
    ctx.page_id = page_id
    source = _source_for(store, job, page, page_id)
    project_id = str(job.get("project_id") or "")
    store.update_status(project_id, page_id, status="running", progress=0, stage="load", error="")
    image = _open_rgb(source)
    progress = _progress(ctx, store, job, page_id)
    check = ctx.cancel_check(str(job.get("id") or ""))

    def analyze():
        pipe, config = _pipeline(ctx, job.get("settings") or {}, reset_clients=True)
        result = pipe.analyze(
            image,
            source,
            config.source_lang,
            config.target_lang,
            progress_callback=progress,
            cancel_check=check,
        )
        return pipe, config, result

    # Замок на весь analyze: детектор один, OCR и переводчик общие.
    # Правка без LLM этот замок не берёт и может идти параллельно.
    with ctx.llm_lock:
        _pipe, config, analyzed = analyze()

    document = PageDocument(
        version=1,
        regions=list(analyzed.regions),
        strokes=[],
        reading_direction=analyzed.reading_direction or "ltr",
        warnings=list(analyzed.warnings),
        timings=dict(analyzed.timings),
        ocr_engine=analyzed.ocr_engine,
        translator_engine=analyzed.translator_engine,
    )
    if _drawable(document.regions, config.translate_sfx):
        _paint(
            job,
            ctx,
            store,
            document,
            "clean",
            page_id,
            source,
            image=image,
            snapshot=True,
            base_version=None,
        )
        return
    store.save_image(project_id, page_id, "result", image)
    store.save_image(project_id, page_id, "thumb", image)
    _commit(store, job, document, page_id, snapshot=True, base_version=None)
    _finish_status(store, job, document, page_id)
    ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(
        store, job, page_id, plan="none", version=document.version,
    )))


def _run_apply(job: dict, ctx: _Runtime) -> None:
    store = _store(job)
    payload = job.get("payload") or {}
    page_id = str(job.get("page_id") or "")
    ctx.page_id = page_id
    plan = str(payload.get("plan") or "typeset")
    if plan not in ("clean", "typeset"):
        plan = "typeset"
    raw = payload.get("document")
    if isinstance(raw, dict):
        document = PageDocument.from_dict(raw)
    elif hasattr(raw, "to_dict"):
        document = PageDocument.from_dict(raw.to_dict())
    else:
        document = store.read_document(str(job.get("project_id") or ""), page_id)
    source = _source_for(store, job, payload, page_id)
    _paint(
        job,
        ctx,
        store,
        document,
        plan,
        page_id,
        source,
        image=None,
        snapshot=False,
        base_version=_base_version(payload),
    )


def _run_region(job: dict, ctx: _Runtime) -> None:
    store = _store(job)
    payload = job.get("payload") or {}
    page_id = str(job.get("page_id") or "")
    ctx.page_id = page_id
    project_id = str(job.get("project_id") or "")
    document = store.read_document(project_id, page_id)
    region_id = int(payload["region_id"])
    region = next(item for item in document.regions if int(item.id) == region_id)
    old_text = region.text
    old_translation = region.translation
    source = _source_for(store, job, payload, page_id)
    image = _open_rgb(source)
    kind = job.get("kind")

    def edit() -> None:
        pipe, config = _pipeline(ctx, job.get("settings") or {}, reset_clients=True)
        if kind == "recognize":
            pipe.recognize_region(image, region)
        elif kind == "retranslate":
            pipe.retranslate_region(
                image,
                document.regions,
                region_id,
                config.source_lang,
                config.target_lang,
            )
        else:
            pipe.shorten_region(region, config.target_lang)

    with ctx.llm_lock:
        edit()

    if region.text != old_text:
        plan = "clean"
    elif region.translation != old_translation:
        plan = "typeset"
    else:
        plan = ""
    if not plan:
        saved = _commit_fresh(
            store, job, document, page_id, snapshot=False, base_version=_base_version(payload),
        )
        if saved is None:
            ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(store, job, page_id, plan="none")))
            return
        ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(
            store, job, page_id, plan="none", version=saved.version,
        )))
        return
    _paint(
        job,
        ctx,
        store,
        document,
        plan,
        page_id,
        source,
        image=image,
        snapshot=False,
        base_version=_base_version(payload),
    )


def _run_export(job: dict, ctx: _Runtime) -> None:
    payload = job.get("payload") or {}
    dest = payload.get("dest")
    if not dest:
        raise RuntimeError("Не задана папка экспорта")
    archive = str(payload.get("archive") or "folder").lower()
    page_ids = [str(item) for item in payload.get("page_ids") or []]
    fmt = str(payload.get("format") or payload.get("fmt") or "png")
    quality = int(payload.get("jpeg_quality") or 90)
    content = str(payload.get("content") or "result")
    project_id = str(job.get("project_id") or "")
    if archive in ("zip", "cbz"):
        from src.app.export import export_archive

        result = export_archive(
            _store(job),
            project_id,
            page_ids,
            Path(dest),
            archive=archive,
            fmt=fmt,
            jpeg_quality=quality,
            content=content,
            name_template=str(payload.get("name_template") or "{chapter}/{index:03}_{stem}"),
            only_ready=bool(payload.get("only_ready")),
        )
    else:
        from src.app.export import export_pages

        result = export_pages(
            _store(job),
            project_id,
            page_ids,
            Path(dest),
            fmt,
            quality,
            str(payload.get("conflict") or "rename"),
            content=content,
        )
    if result.errors:
        raise RuntimeError("; ".join(result.errors))
    event = {
        **_dict_ids(job),
        "plan": "export",
        "paths": [str(path) for path in result.paths],
    }
    skipped = getattr(result, "skipped", None)
    if archive in ("zip", "cbz"):
        event["skipped"] = list(skipped or [])
    ctx.emit(WorkerEvent(PAGE_UPDATED, event))


def _paint(
    job: dict,
    ctx: _Runtime,
    store: ProjectStore,
    document: PageDocument,
    plan: str,
    page_id: str,
    source: str,
    *,
    image: Image.Image | None,
    snapshot: bool,
    base_version: int | None,
) -> None:
    """Очистка под замком LaMa и вёрстка. Снимок auto пишется только для перевода."""
    project_id = str(job.get("project_id") or "")
    warnings = document.warnings
    check = ctx.cancel_check(str(job.get("id") or ""))
    progress = _progress(ctx, store, job, page_id)
    clean_path = store.image_path(project_id, page_id, "clean")
    need_clean = plan == "clean" or not clean_path.is_file()
    if need_clean:
        page_image = image if image is not None else _open_rgb(source)
        with ctx.lama_lock:
            pipe, _config = _pipeline(ctx, job.get("settings") or {}, reset_clients=False)
            mask, cleaned = pipe.clean(
                page_image,
                document.regions,
                strokes=list(document.strokes),
                warnings=warnings,
                progress_callback=progress,
                cancel_check=check,
            )
        _save_mask(store, project_id, page_id, mask)
        store.save_image(project_id, page_id, "clean", cleaned)
    else:
        cleaned = _open_rgb(clean_path)

    with ctx.typeset_lock:
        pipe, config = _pipeline(ctx, job.get("settings") or {}, reset_clients=False)
        drawable = _drawable(document.regions, config.translate_sfx)
        rendered, overflow = pipe.typeset_image(
            cleaned,
            drawable,
            config.target_lang,
            warnings,
            progress_callback=progress,
            cancel_check=check,
        )
    overflow_ids = set(overflow)
    for region in document.regions:
        region.overflow = region.id in overflow_ids
    document.warnings = warnings
    saved = _commit_fresh(
        store,
        job,
        document,
        page_id,
        snapshot=snapshot,
        base_version=base_version,
    )
    plan_name = "clean" if need_clean else "typeset"
    if saved is None:
        ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(store, job, page_id, plan=plan_name)))
        return
    store.save_image(project_id, page_id, "result", rendered)
    store.save_image(project_id, page_id, "thumb", rendered)
    _finish_status(store, job, document, page_id)
    ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(
        store, job, page_id, plan=plan_name, version=saved.version,
    )))


def _pipeline(ctx: _Runtime, settings: dict, *, reset_clients: bool):
    """Один PagePipeline на процесс. Импорт тяжёлого модуля — только здесь."""
    from src.app.settings import AppSettings
    from src.page_pipeline import PagePipeline

    config = AppSettings.from_dict(settings or {}).to_config()
    if ctx.pipeline is None:
        with ctx.init_lock:
            if ctx.pipeline is None:
                ctx.pipeline = PagePipeline(config)
    pipe = ctx.pipeline
    signature = (
        config.llm_base_url,
        config.llm_model,
        bool(config.llm_thinking),
        int(config.llm_timeout),
        config.ocr_backend,
        config.translator_backend,
        config.inpainter_backend,
        config.device,
        config.glossary_path,
    )
    if reset_clients and signature != ctx.clients_sig:
        pipe.ocr = None
        pipe.translator = None
        pipe.ocr_name = ""
        pipe.translator_name = ""
        pipe._llm_down = False
        if ctx.clients_sig is not None and ctx.clients_sig[6:8] != signature[6:8]:
            pipe.inpainter = None
        ctx.clients_sig = signature
    pipe.config = config
    pipe.typesetter.min_font_size = config.min_font_size
    pipe.typesetter.max_font_size = max(config.min_font_size, config.max_font_size)
    pipe.typesetter.stroke_ratio = config.text_stroke_ratio
    pipe.typesetter.margin_ratio = config.text_margin
    pipe.typesetter.lang = config.target_lang
    return pipe, config


def _drawable(regions, translate_sfx: bool) -> list:
    from src.models import should_translate

    return [
        region
        for region in regions
        if region.translation.strip() and should_translate(region, translate_sfx)
    ]


def _commit(
    store: ProjectStore,
    job: dict,
    document: PageDocument,
    page_id: str,
    *,
    snapshot: bool,
    base_version: int | None,
) -> PageDocument:
    project_id = str(job.get("project_id") or "")
    if snapshot:
        store.write_auto(project_id, page_id, PageDocument.from_dict(document.to_dict()))
    return store.write_document(project_id, page_id, document, base_version=base_version)


def _commit_fresh(
    store: ProjectStore,
    job: dict,
    document: PageDocument,
    page_id: str,
    *,
    snapshot: bool,
    base_version: int | None,
) -> PageDocument | None:
    """Записать вёрстку. ``None`` — на диске уже более новая правка, результат отброшен."""
    if base_version is None:
        return _commit(
            store, job, document, page_id, snapshot=snapshot, base_version=None,
        )
    try:
        return _commit(
            store, job, document, page_id, snapshot=snapshot, base_version=base_version,
        )
    except VersionConflict:
        logger.info("Правка страницы %s новее вёрстки, результат отброшен", page_id)
        _release_running(store, job, page_id)
        return None


def _release_running(store: ProjectStore, job: dict, page_id: str) -> None:
    """Прогресс вёрстки ставит «running». Если более новая задача уже не бежит, вернуть «edited»."""
    project_id = str(job.get("project_id") or "")
    try:
        current = store.page_status(project_id, page_id)
    except (FileNotFoundError, OSError, ValueError):
        return
    if current.get("status") != "running":
        return
    try:
        store.update_status(project_id, page_id, status="edited", stage="", error="")
    except (FileNotFoundError, OSError, ValueError):
        return


def _page_update(store: ProjectStore, job: dict, page_id: str, **extra) -> dict:
    """Событие страницы вместе со статусом из стора, чтобы строка списка не зависала."""
    payload = {**_dict_ids(job, page_id), **extra}
    try:
        current = store.page_status(str(job.get("project_id") or ""), page_id)
    except (FileNotFoundError, OSError, ValueError):
        return payload
    payload["status"] = current.get("status") or ""
    payload["progress"] = int(current.get("progress") or 0)
    payload["stage"] = str(current.get("stage") or "")
    return payload


def _finish_status(store: ProjectStore, job: dict, document: PageDocument, page_id: str) -> None:
    status = "offline" if _mentions_fallback(document.warnings) else "done"
    store.update_status(
        str(job.get("project_id") or ""),
        page_id,
        status=status,
        progress=100,
        stage="typeset",
        error="",
        warnings=list(document.warnings),
    )


def _job_page_ids(job: dict) -> list[str]:
    found: list[str] = []
    for page in _page_list(job):
        page_id = str(page.get("page_id") or "")
        if page_id and page_id not in found:
            found.append(page_id)
    own = str(job.get("page_id") or "")
    if own and own not in found:
        found.append(own)
    return found


def _close_stuck_pages(
    job: dict,
    *,
    current_id: str,
    error: str,
    fail_current: bool,
    running_status: str = "error",
) -> list[str]:
    """Снять статусы задания, которое уже не выполняется.

    Текущая страница становится ``error`` или ``idle``. Любая другая
    ``running`` — ошибка, хвост ``queued`` — снова ``idle``.
    """
    if not isinstance(job, dict):
        return []
    try:
        store = _store(job)
    except Exception:
        return []
    project_id = str(job.get("project_id") or "")
    ids = _job_page_ids(job)
    if current_id and current_id not in ids:
        ids.append(current_id)
    changed: list[str] = []
    for page_id in ids:
        try:
            current = store.page_status(project_id, page_id)
        except (FileNotFoundError, OSError, ValueError):
            continue
        status = current.get("status")
        if page_id == current_id and current_id:
            new_status = "error" if fail_current else "idle"
            new_error = error if fail_current else ""
        elif status == "running":
            new_status = running_status
            new_error = error if running_status == "error" else ""
        elif status == "queued":
            new_status = "idle"
            new_error = ""
        else:
            continue
        try:
            store.update_status(
                project_id,
                page_id,
                status=new_status,
                progress=0,
                stage="",
                error=new_error,
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
        changed.append(page_id)
    return changed


def _report_stuck_pages(job: dict, ctx: _Runtime, *, error: str, fail_current: bool) -> None:
    current_id = ctx.page_id or str(job.get("page_id") or "")
    try:
        store = _store(job)
    except Exception:
        return
    running_status = "error" if fail_current else "idle"
    for page_id in _close_stuck_pages(
        job,
        current_id=current_id,
        error=error,
        fail_current=fail_current,
        running_status=running_status,
    ):
        ctx.emit(WorkerEvent(PAGE_UPDATED, _page_update(store, job, page_id)))


def demote_restored_running(store: ProjectStore, jobs: list[dict]) -> None:
    """После загрузки очереди страница ждёт продолжения, а не числится идущей."""
    for job in jobs:
        if not isinstance(job, dict):
            continue
        project_id = str(job.get("project_id") or "")
        if not project_id:
            continue
        for page_id in _job_page_ids(job):
            try:
                current = store.page_status(project_id, page_id)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if current.get("status") != "running":
                continue
            try:
                store.update_status(project_id, page_id, status="queued", progress=0, stage="")
            except (FileNotFoundError, OSError, ValueError):
                continue


def _mentions_fallback(warnings: list[str]) -> bool:
    text = "\n".join(str(item) for item in warnings).casefold()
    return "rapidocr" in text or "argos" in text


def _progress(ctx: _Runtime, store: ProjectStore, job: dict, page_id: str):
    def progress(percent, status, stage=""):
        ctx.emit(WorkerEvent(JOB_PROGRESS, {
            **_dict_ids(job, page_id),
            "progress": int(percent),
            "stage": stage or "",
            "status": status or "",
        }))
        try:
            store.update_status(
                str(job.get("project_id") or ""),
                page_id,
                status="running",
                progress=int(percent),
                stage=stage or status or "",
            )
        except Exception:
            return

    return progress


def _save_mask(store: ProjectStore, project_id: str, page_id: str, mask) -> None:
    import numpy as np

    array = np.asarray(mask)
    if array.dtype != np.uint8:
        array = (array > 0).astype("uint8") * 255
    store.save_image(project_id, page_id, "mask", Image.fromarray(array))


def _store(job: dict) -> ProjectStore:
    root = (job.get("payload") or {}).get("store_root")
    if not root:
        raise RuntimeError("В задании нет store_root")
    return ProjectStore(Path(root))


def _page_list(job: dict) -> list[dict]:
    payload = job.get("payload") or {}
    pages = payload.get("pages")
    if isinstance(pages, list) and pages:
        return [item for item in pages if isinstance(item, dict)]
    return [{
        "page_id": job.get("page_id") or "",
        "source_path": payload.get("source_path") or "",
    }]


def _source_for(store: ProjectStore, job: dict, page: dict, page_id: str) -> str:
    explicit = str(page.get("source_path") or "")
    if explicit:
        return explicit
    project = store.open_project(str(job.get("project_id") or ""))
    for item in project.get("pages") or []:
        if str(item.get("id") or "") == page_id:
            found = str(item.get("source_path") or "")
            if found:
                return found
    raise FileNotFoundError(f"Не задан файл страницы {page_id}")


def _base_version(payload: dict) -> int | None:
    if "base_version" not in payload or payload.get("base_version") is None:
        return None
    return int(payload["base_version"])


def _open_rgb(path: str) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        if image.mode != "RGB":
            return image.convert("RGB")
        return image.copy()


def _dict_ids(job: dict, page_id: str | None = None) -> dict:
    return {
        "job_id": str(job.get("id") or ""),
        "project_id": str(job.get("project_id") or ""),
        "page_id": str(job.get("page_id") or "") if page_id is None else str(page_id),
        "kind": str(job.get("kind") or ""),
    }


def _job_ids(job: Job) -> dict:
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "page_id": job.page_id,
        "kind": job.kind,
    }


def queue_has_unfinished(path: str | Path) -> bool:
    """В сохранённой очереди есть ещё не взятые или оборванные задания.

    Смотрит списки ``batch``, ``edits`` и ``running``. Нет файла или JSON
    не читается — ``False``. Сервер показывает это при старте.
    """
    source = Path(path)
    if not source.is_file():
        return False
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if not isinstance(data, dict):
        return False
    for key in ("batch", "edits", "running"):
        items = data.get(key)
        if isinstance(items, list) and len(items) > 0:
            return True
    return False


def _result_ready(store: ProjectStore, project_id: str, page_id: str) -> bool:
    """У страницы уже есть ``result.png`` — повторный перевод можно пропустить."""
    if not project_id or not page_id:
        return False
    try:
        return store.image_path(project_id, page_id, "result").is_file()
    except (ValueError, OSError):
        return False


def _log_failure(exc: Exception) -> None:
    try:
        from src.utils.logger import logger

        logger.exception("Задание воркера упало: %s", exc)
    except Exception:
        return
