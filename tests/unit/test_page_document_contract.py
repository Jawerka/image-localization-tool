"""Общий контракт документа: Python, JS и Dart читают один fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.document import PageDocument
from src.models import TextRegion

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "page_document_contract.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_roundtrip_keeps_geometry_and_unknown_fields():
    data = _payload()
    for case in data["documents"]:
        raw = case["document"]
        document = PageDocument.from_dict(raw)
        dumped = document.to_dict()
        first = dumped["regions"][0]
        original = raw["regions"][0]
        if original.get("text_position") is not None:
            assert first["text_position"] == list(map(float, original["text_position"]))
        warp = (original.get("style") or {}).get("warp")
        if isinstance(warp, dict):
            restored = first["style"]["warp"]
            assert restored["version"] == warp["version"]
            assert restored["kind"] == warp["kind"]
        if "layout_snapshot" in original:
            assert first["layout_snapshot"]["version"] == 1
        if "future_flag" in raw:
            assert dumped["future_flag"] == "keep-me"


@pytest.mark.parametrize("case", _payload()["invalid"], ids=lambda item: item["name"])
def test_invalid_text_position_rejected(case):
    raw = {
        "id": 1,
        "bbox": [0, 0, 10, 10],
        case["field"]: case["value"],
    }
    with pytest.raises(ValueError):
        TextRegion.from_dict(raw)
