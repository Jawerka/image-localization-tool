"""События процесса-воркера для очереди и будущего SSE."""

from __future__ import annotations

from dataclasses import dataclass, field

JOB_STARTED = "job.started"
JOB_PROGRESS = "job.progress"
PAGE_UPDATED = "page.updated"
JOB_FINISHED = "job.finished"
JOB_FAILED = "job.failed"
JOB_CANCELLED = "job.cancelled"
WORKER_RESTARTING = "worker.restarting"
WORKER_FAILED = "worker.failed"
LLM_STATUS = "llm.status"

EVENT_TYPES = (
    JOB_STARTED,
    JOB_PROGRESS,
    PAGE_UPDATED,
    JOB_FINISHED,
    JOB_FAILED,
    JOB_CANCELLED,
    WORKER_RESTARTING,
    WORKER_FAILED,
    LLM_STATUS,
)


@dataclass
class WorkerEvent:
    """Одно событие: тип и произвольная полезная нагрузка."""

    type: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "payload": dict(self.payload)}
