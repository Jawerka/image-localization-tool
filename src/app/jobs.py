"""Задания и две логические очереди: пакет и правки.

Снимок настроек копируется в задание в момент постановки. Воркер файл
настроек не читает. Правки уходят в воркер сразу и не ждут окончания пакета.
Пауза держит новые задания в очереди. ``save`` / ``load`` пишут снимок в JSON.
"""

from __future__ import annotations

import copy
import json
import queue
import threading
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
    return "batch" if job.kind in BATCH_KINDS else "edit"


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
    порядке, и не ждут, пока пакет допереведёт страницу. Замок LLM ставит
    сам воркер по флагу ``needs_llm``.

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
        self._batch: list[Job] = []
        self._edits: list[Job] = []
        self._jobs: dict[str, Job] = {}
        self._status: dict[str, str] = {}
        self._inflight_batch: str | None = None
        self._inflight_edits: list[str] = []
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
            else:
                self._edits.append(job)
        self._pump()
        return job

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

    def cancel(self, job_id: str | None = None) -> None:
        """Поставить флаг, снять неначатые задания и вызвать ``worker.cancel``."""
        self.cancel_requested = True
        removed: list[Job] = []
        with self._lock:
            if job_id is None:
                removed.extend(self._batch)
                removed.extend(self._edits)
                self._batch.clear()
                self._edits.clear()
            else:
                removed.extend(job for job in self._batch if job.id == job_id)
                removed.extend(job for job in self._edits if job.id == job_id)
                self._batch = [job for job in self._batch if job.id != job_id]
                self._edits = [job for job in self._edits if job.id != job_id]
            for job in removed:
                self._status[job.id] = "cancelled"
        for job in removed:
            self._events.put(WorkerEvent(JOB_CANCELLED, _job_payload(job)))
        self.worker.cancel(job_id)

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
        self._events.put(event)
        if event.type not in _TERMINAL:
            return
        job_id = str(event.payload.get("job_id") or "")
        with self._lock:
            if job_id and job_id == self._inflight_batch:
                self._inflight_batch = None
            if job_id:
                self._inflight_edits = [item for item in self._inflight_edits if item != job_id]
                self._status[job_id] = _STATUS_BY_EVENT[event.type]
        self._pump()

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

    def snapshot(self) -> dict:
        """Пауза, очереди полос и статусы всех известных заданий."""
        with self._lock:
            return {
                "paused": self.paused,
                "batch": [job.to_dict() for job in self._batch],
                "edits": [job.to_dict() for job in self._edits],
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
                self._status[job_id] = "queued"
                lane = self._batch if job.kind in BATCH_KINDS else self._edits
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
              "running": [{"status": "running", "lane": "batch"|"edit", "job": {...}}],
              "history": [{"status": "done"|"error"|"cancelled", "job": {...}}]
            }

        ``batch`` и ``edits`` — ещё не отданные задания, порядок полосы сохранён.
        ``running`` — то, что уже у воркера. ``history`` — завершённые, в том
        числе ``error``, чтобы после ``load`` сработал ``retry_failed``.
        """
        destination = Path(path)
        with self._lock:
            payload = self._dump_locked()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

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
        with self._lock:
            self._restore_locked(data)

    def _pump(self) -> None:
        outgoing: list[tuple[str, Job]] = []
        with self._lock:
            if self.paused:
                return
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
            try:
                self.worker.submit(job)
            except Exception as exc:
                if job.id == self._inflight_batch:
                    with self._lock:
                        if self._inflight_batch == job.id:
                            self._inflight_batch = None
                self.push_event(WorkerEvent("job.failed", {**_job_payload(job), "error": str(exc)}))

    def _dump_locked(self) -> dict:
        running: list[dict] = []
        for job_id in self._inflight_edits:
            job = self._jobs.get(job_id)
            if job is None:
                continue
            running.append({"status": "running", "lane": "edit", "job": job.to_dict()})
        if self._inflight_batch:
            job = self._jobs.get(self._inflight_batch)
            if job is not None:
                running.append({"status": "running", "lane": "batch", "job": job.to_dict()})
        live = {item["job"]["id"] for item in running}
        live.update(job.id for job in self._batch)
        live.update(job.id for job in self._edits)
        history: list[dict] = []
        for job_id, status in self._status.items():
            if job_id in live or status not in _HISTORY_STATUSES:
                continue
            job = self._jobs.get(job_id)
            if job is None:
                continue
            history.append({"status": status, "job": job.to_dict()})
        return {
            "paused": bool(self.paused),
            "batch": [{"status": "queued", "job": job.to_dict()} for job in self._batch],
            "edits": [{"status": "queued", "job": job.to_dict()} for job in self._edits],
            "running": running,
            "history": history,
        }

    def _restore_locked(self, data: dict) -> None:
        self._batch = []
        self._edits = []
        self._jobs = {}
        self._status = {}
        self._inflight_batch = None
        self._inflight_edits = []
        self.paused = bool(data.get("paused"))
        placed: set[str] = set()
        front_batch: list[Job] = []
        front_edits: list[Job] = []
        queued_batch: list[Job] = []
        queued_edits: list[Job] = []

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
            if lane not in ("batch", "edit"):
                lane = _lane_of(job)
            place(job, front_batch if lane == "batch" else front_edits)
        for item in _as_list(data.get("batch")):
            job, _record = _stored_job(item)
            if job is not None:
                place(job, queued_batch)
        for item in _as_list(data.get("edits")):
            job, _record = _stored_job(item)
            if job is not None:
                place(job, queued_edits)
        self._batch = front_batch + queued_batch
        self._edits = front_edits + queued_edits
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
