"""Отмена и callback пайплайна без загрузки моделей."""

import pytest
from PIL import Image

from src.errors import PipelineCancelled
from src.models import TextRegion
from src.page_pipeline import PagePipeline


class _BoomDetector:
    def detect(self, image):
        raise AssertionError("детектор не должен запускаться")


class _EmptyDetector:
    def detect(self, image):
        return []


class _OverflowThenFit:
    """Первый render — overflow, дальше — ок (как после shorten)."""

    def __init__(self):
        self.calls = 0

    def render(self, image, regions, force=False):
        self.calls += 1
        if force or self.calls > 1:
            return image, []
        return image, [5]


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


def test_typeset_prepares_translator_before_shorten():
    """apply_document / typeset часто без translator — shorten не должен падать на None."""
    typesetter = _OverflowThenFit()
    pipeline = PagePipeline(typesetter=typesetter)
    assert pipeline.translator is None
    region = TextRegion(
        id=5,
        bbox=(0, 0, 40, 20),
        text="hello world",
        translation="очень длинный перевод который не влезает в рамку",
    )
    warnings: list[str] = []
    pipeline._typeset(Image.new("RGB", (80, 40), "white"), [region], "ru", warnings)
    assert pipeline.translator is not None
    assert not any("NoneType" in item for item in warnings)
    assert typesetter.calls >= 2
