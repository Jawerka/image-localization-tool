"""Тесты утилит paths."""

import os
import sys
from pathlib import Path

from src.utils.paths import (
    bundle_root,
    components_root,
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

    def _frozen_app(self, tmp_path, monkeypatch, with_legacy: bool) -> tuple[Path, Path | None]:
        app = tmp_path / "app"
        app.mkdir()
        legacy = tmp_path / "local" / "ImageLocalizationTool" / "components"
        if with_legacy:
            legacy.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr("src.utils.paths.install_root", lambda: app)
        monkeypatch.delenv("ILT_COMPONENT_ROOT", raising=False)
        monkeypatch.delenv("ILT_COMPONENT_PREVIOUS_ROOT", raising=False)
        return app, legacy if with_legacy else None

    def test_frozen_components_live_next_to_program(self, tmp_path, monkeypatch):
        app, _legacy = self._frozen_app(tmp_path, monkeypatch, with_legacy=False)
        assert components_root() == app
        assert "ILT_COMPONENT_PREVIOUS_ROOT" not in os.environ

    def test_old_appdata_components_are_not_read(self, tmp_path, monkeypatch):
        app, _legacy = self._frozen_app(tmp_path, monkeypatch, with_legacy=True)
        assert components_root() == app
        assert "ILT_COMPONENT_PREVIOUS_ROOT" not in os.environ

    def test_components_root_explicit_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ILT_COMPONENT_ROOT", str(tmp_path / "chosen"))
        assert components_root() == tmp_path / "chosen"


def test_ilt_data_dir_with_spaces_and_cyrillic(tmp_path, monkeypatch):
    from src.app.paths import data_root, ensure_data_root, settings_path

    root = tmp_path / "Мои данные" / "app data"
    monkeypatch.setenv("ILT_DATA_DIR", str(root))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert data_root() == root
    created = ensure_data_root()
    assert created == root
    assert settings_path() == root / "settings.json"
    assert not (tmp_path / "AppData" / "Roaming").exists()
    assert not (tmp_path / "AppData" / "Local").exists()


def test_default_data_root_stays_in_install_folder(tmp_path, monkeypatch):
    from src.app import paths as app_paths

    app = tmp_path / "ImageLocalizationTool"
    monkeypatch.setattr(app_paths, "install_root", lambda: app)
    monkeypatch.delenv("ILT_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert app_paths.data_root() == app / "data"
    assert app_paths.settings_path() == app / "data" / "settings.json"
    assert app_paths.projects_dir() == app / "data" / "projects"
