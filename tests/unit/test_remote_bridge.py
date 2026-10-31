"""Мост удалённого задания: успех, сбой перевода, уже готовое задание."""

from __future__ import annotations

from src.app.remote_bridge import run_remote_job


class _Job:
    """Подставное задание: считает вызовы finish и fail."""

    def __init__(self, status: str = "queued", project_id: str = "p1", page_id: str = "pg1"):
        self.status = status
        self.project_id = project_id
        self.page_id = page_id
        self.finish_calls: list[bytes] = []
        self.fail_calls: list[str] = []

    def finish(self, png: bytes) -> None:
        self.finish_calls.append(png)

    def fail(self, message: str) -> None:
        self.fail_calls.append(message)


def test_success_finishes_with_png_bytes():
    """Успех: finish один раз с байтами PNG, fail не вызывается."""
    job = _Job()
    seen: list[tuple[str, str]] = []

    def translate_page(project_id: str, page_id: str) -> bytes:
        seen.append((project_id, page_id))
        return b"png-bytes"

    run_remote_job(job, translate_page)

    assert seen == [("p1", "pg1")]
    assert job.finish_calls == [b"png-bytes"]
    assert job.fail_calls == []


def test_failure_fails_with_boom_message():
    """Сбой перевода: fail со строкой, где есть «boom»; finish не вызывается."""
    job = _Job()

    def translate_page(project_id: str, page_id: str) -> bytes:
        raise RuntimeError("boom")

    run_remote_job(job, translate_page)

    assert job.finish_calls == []
    assert len(job.fail_calls) == 1
    assert isinstance(job.fail_calls[0], str)
    assert "boom" in job.fail_calls[0]


def test_already_done_skips_translate():
    """Статус done: перевод, finish и fail не вызываются."""
    job = _Job(status="done")
    called = False

    def translate_page(project_id: str, page_id: str) -> bytes:
        nonlocal called
        called = True
        return b"png-bytes"

    run_remote_job(job, translate_page)

    assert called is False
    assert job.finish_calls == []
    assert job.fail_calls == []
