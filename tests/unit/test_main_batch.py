"""Пакетный CLI: порядок файлов, пропуск готовых и каркас report.json.

Модели не запускаются: проверяется только ``plan_batch_io``.
"""

import json

from PIL import Image

from src.main import build_parser, plan_batch_io, write_batch_report


def _png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "white").save(path)


def test_parser_has_folder_flags():
    args = build_parser().parse_args(["folder", "out", "--recursive", "--skip-existing"])
    assert args.recursive is True
    assert args.skip_existing is True
    plain = build_parser().parse_args(["page.png"])
    assert plain.recursive is False
    assert plain.skip_existing is False


def test_plan_batch_io_orders_skips_and_writes_report(tmp_path):
    root = tmp_path / "in"
    _png(root / "page10.png")
    _png(root / "page2.png")
    _png(root / "notes-mask.png")
    _png(root / "nested" / "page1.png")
    (root / "readme.txt").write_text("x", encoding="utf-8")

    out = tmp_path / "out"
    shallow = plan_batch_io(root, out, recursive=False, skip_existing=False)
    assert [item["name"] for item in shallow["pages"]] == ["page2.png", "page10.png"]
    assert shallow["skipped"] == []
    assert shallow["errors"] == []

    existing = out / "page2_translated.png"
    existing.parent.mkdir()
    existing.write_bytes(b"old")
    planned = plan_batch_io(root, out, recursive=True, skip_existing=True)
    assert [item["name"] for item in planned["pages"]] == ["page1.png", "page10.png"]
    assert planned["skipped"] == [{
        "source": str(root / "page2.png"),
        "destination": str(existing),
        "name": "page2.png",
        "reason": "уже есть",
    }]

    report_path = write_batch_report(planned)
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(saved) == {"pages", "errors", "skipped"}
    assert [item["name"] for item in saved["pages"]] == ["page1.png", "page10.png"]
    assert saved["errors"] == []
    assert saved["skipped"][0]["reason"] == "уже есть"
    assert report_path == out / "report.json"
