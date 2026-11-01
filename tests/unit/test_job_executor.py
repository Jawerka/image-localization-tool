"""Экспорт идёт через вынесенный исполнитель."""

from src.app.job_executor import run_export


def test_run_export_delegates_to_worker(monkeypatch):
    called = {}

    def fake(job, ctx):
        called["job"] = job
        return {"ok": True}

    monkeypatch.setattr("src.app.worker._run_export", fake)
    result = run_export({"kind": "export"}, object())
    assert result == {"ok": True}
    assert called["job"]["kind"] == "export"
