"""Отмена и callback пайплайна без загрузки моделей."""

import numpy as np
import pytest
from PIL import Image

from src.app.export import export_pages
from src.app.store import ProjectStore
from src.components.typesetter import Typesetter
from src.config import Config
from src.errors import PipelineCancelled
from src.models import TextRegion, TextStyle
from src.page_pipeline import PagePipeline


class _BoomDetector:
    def detect(self, image):
        raise AssertionError("детектор не должен запускаться")


class _EmptyDetector:
    def detect(self, image):
        return []


class _AlwaysOverflow:
    """Render всегда с overflow; запоминает force."""

    def __init__(self):
        self.calls = 0
        self.last_force = None

    def render(self, image, regions, force=False):
        self.calls += 1
        self.last_force = force
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


def test_typeset_does_not_auto_shorten_on_overflow():
    """Overflow только варнит; перевод и translator не трогаем."""
    typesetter = _AlwaysOverflow()
    pipeline = PagePipeline(typesetter=typesetter)
    assert pipeline.translator is None
    original = "очень длинный перевод который не влезает в рамку"
    region = TextRegion(
        id=5,
        bbox=(0, 0, 40, 20),
        text="hello world",
        translation=original,
    )
    warnings: list[str] = []
    pipeline._typeset(Image.new("RGB", (80, 40), "white"), [region], "ru", warnings)
    assert pipeline.translator is None
    assert region.translation == original
    assert typesetter.calls == 1
    assert typesetter.last_force is True
    assert any("не влез" in item for item in warnings)


def test_frozen_layout_survives_pipeline_and_export(tmp_path):
    """Snapshot не масштабируется и результат совпадает с экспортом."""
    page = Image.new("RGB", (400, 300), "white")
    region = TextRegion(
        id=1,
        bbox=(80, 80, 160, 75),
        translation="This is a longer sentence for a rotation layout comparison",
        block_type="dialogue",
        style=TextStyle(),
    )
    seed = Typesetter(min_font_size=10, max_font_size=28, lang="en")
    seed.render_layer(
        page.copy(), [TextRegion.from_dict(region.to_dict())],
        force=True, apply_geometry=False, trim=False,
    )
    snapshot = dict(seed._last_layouts[1])

    frozen = TextRegion.from_dict(region.to_dict())
    frozen.layout_snapshot = snapshot
    frozen.style.rotation = 35
    frozen.style.warp = {"kind": "arc", "bend": 0.3}
    pipeline = PagePipeline(
        config=Config(auto_stylized_fonts=False),
        typesetter=Typesetter(min_font_size=10, max_font_size=28, lang="en"),
    )
    rendered, overflow = pipeline.typeset_image(
        page.copy(), [frozen], "en",
    )

    assert overflow == []
    assert rendered.size == page.size
    assert frozen.bbox == region.bbox
    assert frozen.style.font_size == snapshot["font_size"]
    layout = pipeline.typesetter._last_layouts[1]
    assert layout["font_size"] == snapshot["font_size"]
    assert layout["lines"] == snapshot["lines"]

    store = ProjectStore(tmp_path / "store")
    project = store.create_project("Глава", "en", "ru")
    source = tmp_path / "page.png"
    page.save(source)
    page_id = store.add_sources(project["id"], [source])[0]["id"]
    store.save_image(project["id"], page_id, "result", rendered)
    exported = export_pages(
        store, project["id"], [page_id], tmp_path / "out",
        "png", 90, "overwrite",
    )
    assert exported.errors == []
    with Image.open(exported.paths[0]) as saved:
        assert np.array_equal(np.asarray(saved.convert("RGB")), np.asarray(rendered))


def test_incremental_falls_back_when_render_scale_mode_changes():
    """Соседний регион не должен остаться в старой upscale-растеризации."""
    page = Image.new("RGB", (600, 400), "white")
    regions = [
        TextRegion(
            id=1,
            bbox=(60, 60, 160, 75),
            translation="First region with a longer sentence",
            block_type="narration",
        ),
        TextRegion(
            id=2,
            bbox=(320, 60, 160, 75),
            translation="Second unchanged region",
            block_type="narration",
        ),
    ]
    pipeline = PagePipeline(
        config=Config(auto_stylized_fonts=False),
        typesetter=Typesetter(min_font_size=10, max_font_size=28, lang="en"),
    )
    previous, _ = pipeline.typeset_image(
        page.copy(), [TextRegion.from_dict(item.to_dict()) for item in regions], "en",
    )
    previous_regions = [
        TextRegion.from_dict(item.to_dict()) for item in regions
    ]
    previous_bounds = dict(pipeline.typesetter._last_region_bounds)

    seed = Typesetter(min_font_size=10, max_font_size=28, lang="en")
    seed.render_layer(
        page.copy(), [TextRegion.from_dict(regions[0].to_dict())],
        force=True, apply_geometry=False, trim=False,
    )
    snapshot = dict(seed._last_layouts[1])
    current = [TextRegion.from_dict(item.to_dict()) for item in regions]
    current[0].layout_snapshot = snapshot
    current[0].style.rotation = 20

    rendered, _ = pipeline.typeset_image(
        page.copy(),
        [TextRegion.from_dict(item.to_dict()) for item in current],
        "en",
        incremental={
            "previous_regions": previous_regions,
            "previous_result": previous,
            "previous_bounds": previous_bounds,
            "changed_region_ids": [1],
        },
    )
    assert pipeline._last_typeset_details["mode"] == "full"
    full, _ = PagePipeline(
        config=Config(auto_stylized_fonts=False),
        typesetter=Typesetter(min_font_size=10, max_font_size=28, lang="en"),
    ).typeset_image(
        page.copy(), [TextRegion.from_dict(item.to_dict()) for item in current], "en",
    )
    assert np.array_equal(np.asarray(rendered), np.asarray(full))


def test_retypeset_replaces_stale_overflow_warning():
    class Fits:
        def render(self, image, regions, force=False):
            return image, []

    pipeline = PagePipeline(typesetter=Fits())
    warnings = ["Текст не влез полностью: [5]", "OCR: проверить блок 2"]
    pipeline._typeset(Image.new("RGB", (80, 40), "white"), [], "ru", warnings)
    assert warnings == ["OCR: проверить блок 2"]
    pipeline.typesetter = _AlwaysOverflow()
    pipeline._typeset(Image.new("RGB", (80, 40), "white"), [], "ru", warnings)
    pipeline._typeset(Image.new("RGB", (80, 40), "white"), [], "ru", warnings)
    assert warnings.count("Текст не влез полностью: [5]") == 1
