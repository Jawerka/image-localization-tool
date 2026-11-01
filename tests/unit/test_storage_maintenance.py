"""Отчёт о месте и безопасная очистка exports."""

from src.app.project_service import purge_finished_exports, storage_report
from src.app.store import ProjectStore


def test_storage_report_and_purge_keep_active(tmp_path):
    store = ProjectStore(tmp_path)
    exports = tmp_path / "exports"
    active = exports / "keepme"
    stale = exports / "stale"
    active.mkdir(parents=True)
    stale.mkdir(parents=True)
    (active / "export.zip").write_bytes(b"aa")
    (stale / "export.zip").write_bytes(b"bbbb")
    (exports / "job-active.json").write_text(
        '{"folder":"keepme","status":"queued"}', encoding="utf-8"
    )
    (exports / "job-stale.json").write_text(
        '{"folder":"stale","status":"done"}', encoding="utf-8"
    )
    (tmp_path / "imports").mkdir()
    (tmp_path / "imports" / "page.png").write_bytes(b"img")
    report = storage_report(store, active_export_ids={"job-active"})
    assert report["exports_bytes"] >= 6
    assert report["imports_bytes"] >= 3
    assert "imports" in report["imports_policy"]
    purged = purge_finished_exports(store, keep_ids={"job-active"})
    assert "job-stale" in purged["removed"]
    assert "job-active" not in purged["removed"]
    assert (exports / "keepme" / "export.zip").is_file()
    assert not (exports / "stale").exists()
