"""Отмена и callback пайплайна без загрузки моделей."""

import pytest
from PIL import Image

from src.errors import PipelineCancelled
from src.page_pipeline import PagePipeline


class _BoomDetector:
    def detect(self, image):
        raise AssertionError("детектор не должен запускаться")


class _EmptyDetector:
    def detect(self, image):
        return []


def test_cancelled_message_defaults_to_otmeneno():
    error = PipelineCancelled()
    assert str(error) == "Отменено"
    assert error.recoverable is False


def test_analyze_cancel_before_detector():
    pipeline = PagePipeline(detector=_BoomDetector())
    with pytest.raises(PipelineCancelled) as caught:
        pipeline.analyze(
            Image.new("RGB", (8, 8), "white"),
            "page.png",
            "en",
            "ru",
            cancel_check=lambda: True,
        )
    assert caught.value.recoverable is False
    assert caught.value.stage == "detect"


def test_analyze_accepts_two_argument_callback():
    seen = []
    pipeline = PagePipeline(detector=_EmptyDetector())
    pipeline.analyze(
        Image.new("RGB", (8, 8), "white"),
        "page.png",
        "en",
        "ru",
        progress_callback=lambda progress, status: seen.append((progress, status)),
    )
    assert (8, "Детекция баллонов и текста") in seen
    assert (20, "Регионов: 0") in seen
