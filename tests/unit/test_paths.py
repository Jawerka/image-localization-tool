"""Тесты утилит paths."""

import sys
from pathlib import Path

from src.utils.paths import (
    bundle_root,
    get_output_path,
    install_root,
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

    def test_install_root_honors_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ILT_INSTALL_ROOT", str(tmp_path))
        assert install_root() == tmp_path

    def test_install_root_defaults_to_project(self, monkeypatch):
        monkeypatch.delenv("ILT_INSTALL_ROOT", raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert install_root() == project_root()
