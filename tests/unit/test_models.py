"""Тесты моделей."""

import pytest
from PIL import Image

from src.models import (
    MaskStroke,
    PageResult,
    TextRegion,
    TextStyle,
    should_translate,
)


class TestPageResult:
    def test_save(self, tmp_path):
        img = Image.new("RGB", (10, 10), "white")
        result = PageResult(
            source_path="test.png",
            output_image=img,
            regions=[],
        )
        out = tmp_path / "out.png"
        result.save(str(out))
        assert out.exists()

    def test_translation_pairs(self):
        regions = [
            TextRegion(id=1, bbox=(0, 0, 10, 10), text="b", translation="б", order=2),
            TextRegion(id=2, bbox=(0, 0, 10, 10), text="a", translation="а", order=1),
        ]
        result = PageResult(
            source_path="x",
            output_image=Image.new("RGB", (10, 10)),
            regions=regions,
        )
        assert result.translation_pairs == [("a", "а"), ("b", "б")]


class TestTextRegion:
    def test_old_dict_without_new_fields(self):
        region = TextRegion.from_dict({
            "id": 1,
            "bbox": [0, 0, 10, 10],
            "text": "Hi",
            "style": {"fill_rgb": [0, 0, 0], "font_size": 16},
        })
        assert region.skip is False
        assert region.manual is False
        assert region.edited is False
        assert region.overflow is False
        assert region.style.font_size_override == 0

    def test_roundtrip_new_fields(self):
        region = TextRegion(
            id=3,
            bbox=(1, 2, 3, 4),
            text="A",
            translation="Б",
            skip=True,
            manual=True,
            edited=True,
            overflow=True,
            style=TextStyle(font_size_override=22, uppercase=True, fill_locked=True),
        )
        restored = TextRegion.from_dict(region.to_dict())
        assert restored.skip is True
        assert restored.manual is True
        assert restored.edited is True
        assert restored.overflow is True
        assert restored.style.font_size_override == 22
        assert restored.style.uppercase is True
        assert restored.style.fill_locked is True

    def test_should_translate_respects_skip(self):
        region = TextRegion(
            id=1,
            bbox=(0, 0, 10, 10),
            text="Hello",
            block_type="dialogue",
            skip=True,
        )
        assert should_translate(region) is False
        region.skip = False
        assert should_translate(region) is True


class TestMaskStroke:
    def test_roundtrip_and_bad_mode(self):
        stroke = MaskStroke.from_dict({
            "mode": "erase",
            "radius": 4,
            "points": [[1, 2], [3, 4]],
        })
        assert stroke.mode == "erase"
        assert stroke.radius == 4
        assert stroke.points == [(1, 2), (3, 4)]
        assert MaskStroke.from_dict(stroke.to_dict()) == stroke
        with pytest.raises(ValueError):
            MaskStroke.from_dict({"mode": "scribble", "radius": 1, "points": []})
