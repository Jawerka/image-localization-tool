"""Тесты утилит paths."""

import sys
from pathlib import Path

from src.utils.paths import (
    bundle_root,
    get_output_path,
    project_root,
    resolve_model,
)


class TestPaths:
    def test_get_output_path(self):
        result = Path(get_output_path("dir/photo.png"))
        assert result.name == "photo_translated.png"
        assert result.parent.name == "dir"

    def test_bundle_root_without_frozen(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        assert bundle_root() == project_root()

    def test_resolve_model_finds_override(self, tmp_path):
        model = tmp_path / "detector.onnx"
        model.write_bytes(b"x")
        assert resolve_model("detector.onnx", override=tmp_path) == model
