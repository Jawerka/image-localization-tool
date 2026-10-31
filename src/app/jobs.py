"""Задания и две логические очереди: пакет и правки.

Снимок настроек копируется в задание в момент постановки. Воркер файл
настроек не читает. Правки уходят в воркер сразу и не ждут окончания пакета.
Пауза держит новые задания в очереди. ``save`` / ``load`` пишут снимок в JSON.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from src.app.events import JOB_CANCELLED, WorkerEvent
from src.app.settings import AppSettings

BATCH_KINDS = frozenset({"translate_page", "translate_all"})
REGION_KINDS = frozenset({"recognize", "retranslate", "shorten"})
_TERMINAL = frozenset({"job.finished", "job.failed", "job.cancelled"})
_STATUS_BY_EVENT = {
    "job.finished": "done",
    "job.failed": "error",
    "job.cancelled": "cancelled",
}
_HISTORY_STATUSES = frozenset({"done", "error", "cancelled"})
logger = logging.getLogger("ilt.app.jobs")


def compute_needs_llm(kind: str, settings: dict) -> bool:
    """Нужен ли замок LLM.

    Распознать, перевести заново и сократить — всегда. Пакетный перевод — если
    в снимке адрес непустой и это не офлайн-пара RapidOCR + Argos.
    Правка документа и экспорт замок не берут.
    """
    if kind in REGION_KINDS:
        return True
    if kind not in BATCH_KINDS:
        return False
    url = str(settings.get("llm_base_url") or "").strip()
    if not url:
        return False
    offline = settings.get("ocr_backend") == "rapid" and settings.get("translator_backend") == "argos"
    return not offline


def _snapshot(settings: AppSettings | dict | None) -> dict:
    if isinstance(settings, AppSettings):
        data = settings.to_dict()
    elif isinstance(settings, dict):
        data = dict(settings)
    else:
        data = AppSettings().to_dict()
    data.pop("api_key", None)
    return copy.deepcopy(data)


def _copy_payload(payload: dict | None) -> dict:
    raw = dict(payload or {})
    try:
        return copy.deepcopy(raw)
    except Exception:
        return raw


def _lane_of(job: Job) -> str:
    if job.kind in BATCH_KINDS:
        return "batch"
    if job.kind == "export":
        return "export"
    return "edit"


@dataclass
class Job:
    """Одно задание воркеру. ``settings`` — снимок без секретов."""

    id: str
    kind: str
    project_id: str
    page_id: str = ""
    settings: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    needs_llm: bool = False
    queued_monotonic: float = field(default_factory=time.monotonic, repr=False, compare=False)
    queue_wait_seconds: float = field(default=0.0, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "project_id": self.project_id,
            "page_id": self.page_id,
            "settings": copy.deepcopy(self.settings),
            "payload": _copy_payload(self.payload),
            "needs_llm": bool(self.needs_llm),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        """Собрать задание из словаря ``to_dict`` (в том числе после JSON)."""
        settings = data.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or ""),
            project_id=str(data.get("project_id") or ""),
            page_id=str(data.get("page_id") or ""),
            settings=copy.deepcopy(settings),
            payload=_copy_payload(payload),
            needs_llm=bool(data.get("needs_llm")),
        )


def skip_ready(job: Job) -> bool:
    """Флаг ``payload["skip_ready"]``.

    Очередь ключ не выкидывает и сохраняет его в JSON. Пропуск готовой
    страницы делает стадия воркера, не очередь.
    """
    return bool(job.payload.get("skip_ready"))


class JobQueue:
    """Очередь поверх воркера с методами ``submit``, ``cancel`` и ``shutdown``.

    Пакет (``translate_page``, ``translate_all``) идёт по одному. Правки,
    включая ``apply_document`` и операции с LLM, отправляются сразу, в своём
    порядке, и не ждут, пока пакет допереведёт страницу. Экспорт идёт
    отдельной полосой: ожидание готового результата не задерживает правки.
    Замок LLM ставит сам воркер по флагу ``needs_llm``.

    ``pause`` останавливает выдачу и пакета, и правок. Уже отданное задание
    воркер может закончить: терминальное событие снимает inflight, но
    следующее не стартует, пока не будет ``resume``. ``submit`` на паузе
    только ставит задание со статусом ``queued``.

    Статусы своих заданий: ``queued``, ``running``, ``done``, ``error``,
    ``cancelled``. Завершённые остаются в истории по id, чтобы ``retry_failed``
    нашёл ошибку после выхода из полосы.
    """

    def __init__(self, worker):
        self.worker = worker
        self.cancel_requested = False
        self.paused = False
        self._events: queue.Queue[WorkerEvent] = queue.Queue()
        self._lock = threading.Lock()
        # submit и cancel отправляются воркеру в одном порядке. RLock, чтобы
        # синхронный FakeWorker мог завершить задание внутри submit.
        self._dispatch_lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._save_path: Path | None = None
        self._batch: list[Job] = []
        self._edits: list[Job] = []
        self._exports: list[Job] = []
        self._jobs: dict[str, Job] = {}
        self._status: dict[str, str] = {}
        self._results: dict[str, dict] = {}
        self._inflight_batch: str | None = None
        self._inflight_edits: list[str] = []
        self._inflight_exports: list[str] = []
        self._closed = False
        if hasattr(worker, "event_sink"):
            worker.event_sink = self.push_event

    def submit(
        self,
        kind: str,
        project_id: str,
        page_id: str = "",
        settings: AppSettings | dict | None = None,
        payload: dict | None = None,
        job_id: str = "",
    ) -> Job:
        """Поставить задание. Снимок настроек фиксируется здесь."""
        if self._closed:
            raise RuntimeError("Очередь остановлена")
        snapshot = _snapshot(settings)
        job = Job(
            id=job_id or uuid.uuid4().hex[:8],
            kind=kind,
            project_id=project_id,
            page_id=page_id or "",
            settings=snapshot,
            payload=_copy_payload(payload),
            needs_llm=compute_needs_llm(kind, snapshot),
        )
        self.cancel_requested = False
        with self._lock:
            self._jobs[job.id] = job
            self._status[job.id] = "queued"
            if kind in BATCH_KINDS:
                self._batch.append(job)
            elif kind == "export":
                self._exports.append(job)
            else:
                self._edits.append(job)
        self._pump()
        return job

    def busy(self) -> bool:
        """Есть ли задания, уже переданные воркеру, включая другие проекты."""
        with self._lock:
            return bool(
                self._inflight_batch
                or self._inflight_edits
                or self._inflight_exports
            )

    def pause(self) -> None:
        """Не отдавать новые задания. Уже отданные воркер может закончить."""
        with self._lock:
            self.paused = True
        _call_worker(self.worker, "pause")

    def resume(self) -> None:
        """Снять паузу и отдать воркеру то, что ждёт в полосах."""
        _call_worker(self.worker, "resume")
        with self._lock:
            self.paused = False
        self._pump()

    def cancel(self, job_id: str | None = None) -> list[Job]:
        """Снять задания и остановить воркер. Возвращает снятые задания.

        Без ``job_id`` это кнопка «Стоп»: очередь пустеет целиком, пауза
        снимается, уже отданное задание тоже помечается отменённым.
        """
        self.cancel_requested = True
        removed: list[Job] = []
        full = job_id is None
        notify_worker = full
        with self._lock:
            if full:
                removed.extend(self._batch)
                removed.extend(self._edits)
                removed.extend(self._exports)
                self._batch.clear()
                self._edits.clear()
                self._exports.clear()
                removed.extend(self._inflight_jobs_locked())
                self._inflight_batch = None
                self._inflight_edits.clear()
                self._inflight_exports.clear()
                self.paused = False
            else:
                inflight = [
                    job for job in self._inflight_jobs_locked() if job.id == job_id
                ]
                notify_worker = bool(inflight)
                removed.extend(inflight)
                removed.extend(job for job in self._batch if job.id == job_id)
                removed.extend(job for job in self._edits if job.id == job_id)
                removed.extend(job for job in self._exports if job.id == job_id)
                self._batch = [job for job in self._batch if job.id != job_id]
                self._edits = [job for job in self._edits if job.id != job_id]
                self._exports = [job for job in self._exports if job.id != job_id]
            for job in removed:
                self._status[job.id] = "cancelled"
                self._results.pop(job.id, None)
            self._trim_results_locked()
        for job in removed:
            self._events.put(WorkerEvent(JOB_CANCELLED, _job_payload(job)))
        if notify_worker:
            # Тот же замок, что у submit: отмена не обгонит отправку задания.
            with self._dispatch_lock:
                self.worker.cancel(job_id)
        if full:
            _call_worker(self.worker, "resume")
        return removed

    def shutdown(self) -> None:
        self._closed = True
        shutdown = getattr(self.worker, "shutdown", None)
        if shutdown is not None:
            shutdown()

    def push_event(self, event: WorkerEvent) -> None:
        """Принять событие воркера. Завершение пакета выпускает следующее задание."""
        if not isinstance(event, WorkerEvent):
            event = WorkerEvent(
                type=str(event.get("type") or ""),
                payload=dict(event.get("payload") or {}),
            )
        if event.type not in _TERMINAL:
            self._events.put(event)
            return
        job_id = str(event.payload.get("job_id") or "")
        changed = False
        duplicate = False
        with self._lock:
            if job_id and job_id == self._inflight_batch:
                self._inflight_batch = None
            if job_id:
                self._inflight_edits = [item for item in self._inflight_edits if item != job_id]
                self._inflight_exports = [
                    item for item in self._inflight_exports if item != job_id
                ]
                # Первое терминальное событие выигрывает: поздний finished
                # не должен перетереть уже выставленный cancelled.
                duplicate = self._status.get(job_id) in _HISTORY_STATUSES
                if not duplicate:
                    self._status[job_id] = _STATUS_BY_EVENT[event.type]
                    self._results[job_id] = dict(event.payload)
                    self._trim_results_locked()
                    changed = True
        if not duplicate:
            self._events.put(event)
        self._pump()
        if changed:
            self._persist()

    def job_result(self, job_id: str) -> dict:
        """Терминальный payload задания: результат экспорта или текст ошибки."""
        with self._lock:
            return dict(self._results.get(job_id) or {})

    def _trim_results_locked(self) -> None:
        """Держать историю, статусы и результаты в одном размере.

        Порядок — по времени завершения (порядок вставки ``_results``), а не
        по порядку постановки: retry не должен выглядеть старым заданием.
        """
        finished = [
            job_id
            for job_id, status in self._status.items()
            if status in _HISTORY_STATUSES
        ]
        ordered = [job_id for job_id in self._results if job_id in finished]
        ordered.extend(
            job_id for job_id in finished if job_id not in self._results
        )
        for job_id in ordered[:max(0, len(ordered) - 200)]:
            self._status.pop(job_id, None)
            self._results.pop(job_id, None)
            self._jobs.pop(job_id, None)

    def _persist(self) -> None:
        path = self._save_path
        if path is None:
            return
        try:
            self.save(path)
        except (OSError, TypeError, ValueError):
            logger.exception("Не удалось сохранить очередь после завершения задания")

    def drain_events(self) -> list[WorkerEvent]:
        items: list[WorkerEvent] = []
        while True:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                return items

    def job_status(self, job_id: str) -> str:
        """Статус задания или пустая строка, если очередь его не видела."""
        with self._lock:
            return self._status.get(job_id, "")

    def job(self, job_id: str) -> Job | None:
        """Задание по id, в том числе уже завершённое или снятое."""
        with self._lock:
            return self._jobs.get(str(job_id or ""))

    def active_job(self, kind: str, page_id: str, project_id: str = "") -> Job | None:
        """Незавершённое задание нужного вида для страницы (для rebake)."""
        with self._lock:
            active = self._inflight_jobs_locked()
            active.extend(self._batch)
            active.extend(self._edits)
            active.extend(self._exports)
            statuses = dict(self._status)
        for job in active:
            if job.kind != kind or str(job.page_id) != str(page_id):
                continue
            if project_id and job.project_id != project_id:
                continue
            if statuses.get(job.id) in _HISTORY_STATUSES:
                continue
            return job
        return None

    def failed_job(self, kind: str, page_id: str, project_id: str = "") -> Job | None:
        """Последнее задание нужного вида, завершившееся ошибкой."""
        with self._lock:
            order = list(reversed(self._results))
            jobs = dict(self._jobs)
            statuses = dict(self._status)
        for job_id in order:
            job = jobs.get(job_id)
            if job is None or statuses.get(job_id) != "error":
                continue
            if job.kind != kind or str(job.page_id) != str(page_id):
                continue
            if project_id and job.project_id != project_id:
                continue
            return job
        return None

    def active_page_ids(self, exclude: str = "", project_id: str = "") -> set[str]:
        """Страницы незавершённых заданий, которые меняют статус страниц.

        Экспорт не меняет статусы, поэтому его страницы сюда не входят.
        """
        with self._lock:
            active = self._inflight_jobs_locked()
            active.extend(self._batch)
            active.extend(self._edits)
            active.extend(self._exports)
            statuses = dict(self._status)
        found: set[str] = set()
        for job in active:
            if job.id == exclude:
                continue
            if job.kind == "export":
                continue
            if statuses.get(job.id) in _HISTORY_STATUSES:
                continue
            if project_id and job.project_id != project_id:
                continue
            found.update(_pages_of(job))
        return found

    def snapshot(self) -> dict:
        """Пауза, очереди полос и статусы всех известных заданий."""
        with self._lock:
            return {
                "paused": self.paused,
                "batch": [job.to_dict() for job in self._batch],
                "edits": [job.to_dict() for job in self._edits],
                "exports": [job.to_dict() for job in self._exports],
                "statuses": dict(self._status),
            }

    def retry_failed(self) -> list[Job]:
        """Снова поставить задания со статусом ``error``.

        Те же объекты возвращаются в свою полосу со статусом ``queued`` и
        пропадают из набора ошибок, поэтому повторный вызов их не дублирует.
        Без паузы очередь сразу зовёт ``_pump``. На паузе они остаются ``queued``.
        """
        requeued: list[Job] = []
        with self._lock:
            failed_ids = [job_id for job_id, status in self._status.items() if status == "error"]
            for job_id in failed_ids:
                job = self._jobs.get(job_id)
                if job is None:
                    self._status.pop(job_id, None)
                    continue
                # Переставить в конец истории: после нового завершения задание
                # не должно считаться старым и обрезаться первым.
                self._status.pop(job_id, None)
                self._status[job_id] = "queued"
                self._results.pop(job_id, None)
                if job.kind in BATCH_KINDS:
                    lane = self._batch
                elif job.kind == "export":
                    lane = self._exports
                else:
                    lane = self._edits
                if not any(item.id == job.id for item in lane):
                    lane.append(job)
                requeued.append(job)
            paused = self.paused
        if not paused:
            self._pump()
        return requeued

    def save(self, path: str | Path) -> None:
        """Записать очередь в UTF-8 JSON.

        Форма::

            {
              "paused": bool,
              "batch": [{"status": "queued", "job": {...to_dict...}}],
              "edits": [{"status": "queued", "job": {...to_dict...}}],
              "exports": [{"status": "queued", "job": {...to_dict...}}],
              "running": [{"status": "running", "lane": "batch"|"edit"|"export", "job": {...}}],
              "history": [{"status": "done"|"error"|"cancelled", "job": {...}, "result": {...}}]
            }

        ``batch``, ``edits`` и ``exports`` — ещё не отданные задания.
        ``running`` — то, что уже у воркера; отменённое или завершённое
        задание сюда не попадает, даже если терминальное событие ещё в пути.
        ``history`` — завершённые, в том числе ``error``, чтобы после ``load``
        сработал ``retry_failed``.
        """
        destination = Path(path)
        # Замок на весь цикл: поздний save не должен записать старый снимок
        # поверх нового, а падение посреди записи — испортить файл.
        with self._save_lock:
            self._save_path = destination
            with self._lock:
                payload = self._dump_locked()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            )
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

    def load(self, path: str | Path) -> None:
        """Восстановить очередь из JSON. Нет файла — ничего не делать.

        ``worker.submit`` не вызывается. Задание из ``running`` (статус
        ``running``) становится ``queued`` и встаёт в начало своей полосы:
        после перезапуска живой воркер не продолжить, повторно его не
        отправляем. Если в файле ``paused`` истинно, пауза остаётся.
        Загруженные ``queued`` не стартуют сами: их заберёт ``resume``
        или следующий ``_pump``, когда паузы нет.
        """
        source = Path(path)
        if not source.is_file():
            return
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        with self._save_lock:
            self._save_path = source
            with self._lock:
                self._restore_locked(data)

    def _pump(self) -> None:
        outgoing: list[tuple[str, Job]] = []
        with self._lock:
            if self.paused:
                return
            while self._exports:
                job = self._exports.pop(0)
                self._status[job.id] = "running"
                self._inflight_exports.append(job.id)
                outgoing.append(("export", job))
            while self._edits:
                job = self._edits.pop(0)
                self._status[job.id] = "running"
                self._inflight_edits.append(job.id)
                outgoing.append(("edit", job))
            if self._inflight_batch is None and self._batch:
                job = self._batch.pop(0)
                self._inflight_batch = job.id
                self._status[job.id] = "running"
                outgoing.append(("batch", job))
        for _lane, job in outgoing:
            with self._dispatch_lock:
                with self._lock:
                    # Между постановкой в running и отправкой могли отменить.
                    if self._status.get(job.id) != "running":
                        self._forget_inflight_locked(job.id)
                        continue
                try:
                    job.queue_wait_seconds = max(0.0, time.monotonic() - job.queued_monotonic)
                    self.worker.submit(job)
                except Exception as exc:
                    with self._lock:
                        self._forget_inflight_locked(job.id)
                    self.push_event(WorkerEvent("job.failed", {**_job_payload(job), "error": str(exc)}))

    def _forget_inflight_locked(self, job_id: str) -> None:
        """Снять задание со всех полос. Вызывать под ``_lock``."""
        if job_id == self._inflight_batch:
            self._inflight_batch = None
        if job_id in self._inflight_edits:
            self._inflight_edits = [item for item in self._inflight_edits if item != job_id]
        if job_id in self._inflight_exports:
            self._inflight_exports = [
                item for item in self._inflight_exports if item != job_id
            ]

    def _inflight_jobs_locked(self) -> list[Job]:
        found: list[Job] = []
        if self._inflight_batch:
            job = self._jobs.get(self._inflight_batch)
            if job is not None:
                found.append(job)
        for job_id in self._inflight_edits:
            job = self._jobs.get(job_id)
            if job is not None:
                found.append(job)
        for job_id in self._inflight_exports:
            job = self._jobs.get(job_id)
            if job is not None:
                found.append(job)
        return found

    def _dump_locked(self) -> dict:
        running: list[dict] = []
        for job_id in self._inflight_edits:
            job = self._jobs.get(job_id)
            if job is None or self._status.get(job_id) in _HISTORY_STATUSES:
                # Уже отменено/завершено, но терминальное событие ещё в пути.
                continue
            running.append({"status": "running", "lane": "edit", "job": job.to_dict()})
        for job_id in self._inflight_exports:
            job = self._jobs.get(job_id)
            if job is None or self._status.get(job_id) in _HISTORY_STATUSES:
                continue
            running.append({"status": "running", "lane": "export", "job": job.to_dict()})
        if self._inflight_batch:
            job = self._jobs.get(self._inflight_batch)
            if job is not None and self._status.get(self._inflight_batch) not in _HISTORY_STATUSES:
                running.append({"status": "running", "lane": "batch", "job": job.to_dict()})
        live = {item["job"]["id"] for item in running}
        live.update(job.id for job in self._batch)
        live.update(job.id for job in self._edits)
        live.update(job.id for job in self._exports)
        history: list[dict] = []
        ordered = [job_id for job_id in self._results if job_id not in live]
        ordered.extend(
            job_id
            for job_id, status in self._status.items()
            if job_id not in live
            and status in _HISTORY_STATUSES
            and job_id not in self._results
        )
        for job_id in ordered:
            status = self._status.get(job_id) or ""
            if status not in _HISTORY_STATUSES:
                continue
            job = self._jobs.get(job_id)
            if job is None:
                continue
            history.append({
                "status": status,
                "job": job.to_dict(),
                "result": dict(self._results.get(job_id) or {}),
            })
        return {
            "paused": bool(self.paused),
            "batch": [{"status": "queued", "job": job.to_dict()} for job in self._batch],
            "edits": [{"status": "queued", "job": job.to_dict()} for job in self._edits],
            "exports": [{"status": "queued", "job": job.to_dict()} for job in self._exports],
            "running": running,
            "history": history,
        }

    def _restore_locked(self, data: dict) -> None:
        self._batch = []
        self._edits = []
        self._exports = []
        self._jobs = {}
        self._status = {}
        self._results = {}
        self._inflight_batch = None
        self._inflight_edits = []
        self._inflight_exports = []
        self.paused = bool(data.get("paused"))
        placed: set[str] = set()
        front_batch: list[Job] = []
        front_edits: list[Job] = []
        front_exports: list[Job] = []
        queued_batch: list[Job] = []
        queued_edits: list[Job] = []
        queued_exports: list[Job] = []

        def place(job: Job, dest: list[Job]) -> None:
            if job.id in placed:
                return
            placed.add(job.id)
            self._jobs[job.id] = job
            self._status[job.id] = "queued"
            dest.append(job)

        for item in _as_list(data.get("running")):
            job, record = _stored_job(item)
            if job is None:
                continue
            lane = record.get("lane")
            if lane not in ("batch", "edit", "export"):
                lane = _lane_of(job)
            if lane == "batch":
                place(job, front_batch)
            elif lane == "export":
                place(job, front_exports)
            else:
                place(job, front_edits)
        for item in _as_list(data.get("batch")):
            job, _record = _stored_job(item)
            if job is not None:
                place(job, queued_batch)
        for item in _as_list(data.get("edits")):
            job, _record = _stored_job(item)
            if job is not None:
                place(job, queued_edits)
        for item in _as_list(data.get("exports")):
            job, _record = _stored_job(item)
            if job is not None:
                place(job, queued_exports)
        self._batch = front_batch + queued_batch
        self._edits = front_edits + queued_edits
        self._exports = front_exports + queued_exports
        for item in _as_list(data.get("history")):
            job, record = _stored_job(item)
            if job is None or job.id in placed:
                continue
            status = record.get("status")
            if status not in _HISTORY_STATUSES:
                continue
            placed.add(job.id)
            self._jobs[job.id] = job
            self._status[job.id] = str(status)
            result = record.get("result")
            # Пустой payload тоже занимает место в истории: иначе trim
            # не сможет упорядочить задание по времени завершения.
            self._results[job.id] = dict(result) if isinstance(result, dict) else {}
        self._trim_results_locked()


def _call_worker(worker: object, name: str) -> None:
    """Сообщить воркеру паузу или продолжение, если такой метод есть."""
    hook = getattr(worker, name, None)
    if callable(hook):
        hook()


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _stored_job(item: object) -> tuple[Job | None, dict]:
    if not isinstance(item, dict):
        return None, {}
    raw = item.get("job") if isinstance(item.get("job"), dict) else item
    if not isinstance(raw, dict):
        return None, item
    job = Job.from_dict(raw)
    if not job.id:
        return None, item
    return job, item


def _job_payload(job: Job) -> dict:
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "page_id": job.page_id,
        "kind": job.kind,
    }


def _pages_of(job: Job) -> list[str]:
    """Страницы задания: своя, ``payload["pages"]`` и ``payload["page_ids"]``."""
    found: list[str] = []
    if job.page_id:
        found.append(str(job.page_id))
    raw = job.payload.get("pages")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            page_id = str(item.get("page_id") or "")
            if page_id and page_id not in found:
                found.append(page_id)
    raw = job.payload.get("page_ids")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, (dict, list)):
                continue
            page_id = str(item or "")
            if page_id and page_id not in found:
                found.append(page_id)
    return found
