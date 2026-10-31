"""Сбой VLM не закрепляет RapidOCR, если фолбэк сам не поднялся."""

from __future__ import annotations

import pytest

from src.config import Config
from src.page_pipeline import PagePipeline


class _Vlm:
    def recognize(self, image, regions, reading_order="auto"):
        raise RuntimeError("битый JSON")


class _RapidOk:
    def __init__(self, min_confidence=0.3, intra_op_threads=0):
        self.calls = 0

    def recognize(self, image, regions, reading_order="auto"):
        self.calls += 1
        return "ltr", regions


class _RapidDown:
    def __init__(self, min_confidence=0.3, intra_op_threads=0):
        pass

    def recognize(self, image, regions, reading_order="auto"):
        raise RuntimeError("Нужно подготовить оффлайн-распознавание")


def _pipe(ocr):
    pipe = PagePipeline(Config(ocr_backend="vlm"))
    pipe.ocr = ocr
    pipe.ocr_name = "vlm"
    return pipe


def test_missing_rapid_keeps_vlm(monkeypatch):
    monkeypatch.setattr("src.page_pipeline.RapidOcr", _RapidDown)
    vlm = _Vlm()
    pipe = _pipe(vlm)
    with pytest.raises(RuntimeError, match="битый JSON"):
        pipe._recognize(None, [], [])
    assert pipe.ocr is vlm
    assert pipe.ocr_name == "vlm"
    assert pipe._llm_down is False


def test_working_rapid_sticks(monkeypatch):
    monkeypatch.setattr("src.page_pipeline.RapidOcr", _RapidOk)
    pipe = _pipe(_Vlm())
    warnings = []
    direction, regions = pipe._recognize(None, ["region"], warnings)
    assert direction == "ltr"
    assert regions == ["region"]
    assert pipe.ocr_name == "rapid"
    assert pipe._llm_down is True
    assert any("OCR переключён на RapidOCR" in item for item in warnings)
