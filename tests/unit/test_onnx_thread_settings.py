"""Проверки передачи настройки потоков ONNX Runtime в движки."""

import sys
import types

from src.components.bubble_detector import BubbleDetector
from src.components.rapid_ocr import RapidOcr


def test_bubble_detector_uses_explicit_intra_op_threads(tmp_path, monkeypatch):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"model")
    created = {}

    class SessionOptions:
        intra_op_num_threads = 0

    def inference_session(path, **kwargs):
        created.update(path=path, **kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(
        SessionOptions=SessionOptions,
        InferenceSession=inference_session,
    ))
    detector = BubbleDetector(model_path=model, intra_op_threads=3)
    detector._load()

    assert created["sess_options"].intra_op_num_threads == 3
    assert created["providers"] == ["CPUExecutionProvider"]


def test_rapid_ocr_passes_explicit_intra_op_threads(monkeypatch):
    received = {}

    class FakeRapidOCR:
        def __init__(self, *, params):
            received.update(params)

    monkeypatch.setitem(sys.modules, "rapidocr", types.SimpleNamespace(RapidOCR=FakeRapidOCR))
    monkeypatch.setattr("src.app.component_catalog.ocr_params", lambda: {"Det.model_path": "det.onnx"})

    RapidOcr(intra_op_threads=4)._load()

    assert received["Det.model_path"] == "det.onnx"
    assert received["EngineConfig.onnxruntime.intra_op_num_threads"] == 4


def test_bubble_detector_leaves_onnx_auto_default_when_threads_are_zero(tmp_path, monkeypatch):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"model")
    received = {}

    def inference_session(path, **kwargs):
        received.update(path=path, **kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(InferenceSession=inference_session))
    BubbleDetector(model_path=model)._load()

    assert "sess_options" not in received
