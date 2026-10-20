"""Настройки приложения: кламп, миграция, ключ в data и пустой адрес LLM."""

import json
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from src.app.paths import (
    AppPaths,
    data_root,
    ensure_data_root,
    is_portable,
    logs_dir,
    projects_dir,
    settings_path,
    using_paths,
)
from src.app.settings import (
    AppSettings,
    get_api_key,
    migrate_legacy_api_key,
    migration_warning,
    set_api_key,
)
from src.config import Config


def test_clamp_limits():
    settings = AppSettings(
        ui_scale=1000,
        llm_timeout=1,
        detector_conf=0.01,
        text_stroke_ratio=2,
        text_margin=2,
        min_font_size=300,
        max_font_size=4,
        export_jpeg_quality=0,
        window_width=100,
        window_height=100,
        window_x=-20,
        recent_projects=[str(index) for index in range(11)],
    )
    assert settings.ui_scale == 150
    assert AppSettings(ui_scale=99).ui_scale == 100
    assert settings.llm_timeout == 10
    assert AppSettings(llm_timeout=99999).llm_timeout == 3600
    assert settings.detector_conf == 0.05
    assert AppSettings(detector_conf=0.99).detector_conf == 0.95
    assert settings.text_stroke_ratio == 0.5
    assert AppSettings(text_stroke_ratio=-1).text_stroke_ratio == 0
    assert settings.text_margin == 0.3
    assert AppSettings(render_cache_limit_mb=-1).render_cache_limit_mb == 0
    assert AppSettings(render_cache_limit_mb=9000).render_cache_limit_mb == 4096
    assert AppSettings(render_cache_limit_mb=128).to_config().render_cache_limit_mb == 128
    assert AppSettings(ort_intra_op_threads=-1).ort_intra_op_threads == 0
    assert AppSettings(ort_intra_op_threads=999).ort_intra_op_threads == 256
    assert AppSettings(ort_intra_op_threads=4).to_dict()["ort_intra_op_threads"] == 4
    assert AppSettings(ort_intra_op_threads=4).to_config().ort_intra_op_threads == 4
    assert AppSettings(device="gpu").device == "cuda"
    assert AppSettings(device="GPU").to_config().device == "cuda"
    assert AppSettings(text_margin=-1).text_margin == 0
    assert AppSettings().text_margin == 0.08
    assert AppSettings().to_dict()["text_margin"] == 0.08
    assert AppSettings().to_config().text_margin == 0.08
    assert settings.export_jpeg_quality == 1
    assert settings.min_font_size <= settings.max_font_size
    assert 8 <= settings.min_font_size <= 256
    assert 8 <= settings.max_font_size <= 256
    assert settings.window_width == 1100
    assert settings.window_height == 700
    assert settings.window_x == -20
    assert AppSettings().window_width is None
    assert settings.recent_projects == [str(index) for index in range(10)]


def test_dock_position_normalizes():
    assert AppSettings().dock_position == "bottom"
    assert AppSettings(dock_position="top").dock_position == "top"
    assert AppSettings(dock_position="TOP").dock_position == "top"
    assert AppSettings(dock_position="side").dock_position == "bottom"
    assert AppSettings(dock_position="top").to_dict()["dock_position"] == "top"
    assert AppSettings.from_dict({"dock_position": "top"}).dock_position == "top"
    assert AppSettings.from_dict({"dock_position": 3}).dock_position == "bottom"


def test_viewer_layers_default_true_and_persist(tmp_path):
    assert AppSettings().viewer_show_boxes is True
    assert AppSettings().viewer_show_mask is True
    assert Config().viewer_show_boxes is True
    assert Config().viewer_show_mask is True

    for boxes in (False, True):
        for mask in (False, True):
            path = tmp_path / f"layers-{boxes}-{mask}.json"
            AppSettings(viewer_show_boxes=boxes, viewer_show_mask=mask).save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["viewer_show_boxes"] is boxes
            assert payload["viewer_show_mask"] is mask
            loaded, warnings = AppSettings.load(path)
            assert warnings == []
            assert loaded.viewer_show_boxes is boxes
            assert loaded.viewer_show_mask is mask

    path = tmp_path / "old-settings.json"
    path.write_text(json.dumps({"schema": 1, "theme": "dark"}), encoding="utf-8")
    old, warnings = AppSettings.load(path)
    assert warnings == []
    assert old.viewer_show_boxes is True
    assert old.viewer_show_mask is True

    fallback = AppSettings.from_dict(
        {"viewer_show_boxes": "maybe", "viewer_show_mask": 0}
    )
    assert fallback.viewer_show_boxes is True
    assert fallback.viewer_show_mask is False


def test_missing_file_and_empty_llm_url(tmp_path):
    settings, warnings = AppSettings.load(tmp_path / "missing.json")
    assert warnings == []
    assert settings.llm_base_url == ""
    assert not (tmp_path / "missing.json").exists()
    config = settings.to_config()
    assert config.llm_base_url == ""
    assert Config().llm_base_url != ""
    custom = AppSettings(llm_base_url="http://127.0.0.1:9/v1").to_config()
    assert custom.llm_base_url == "http://127.0.0.1:9/v1"


def test_ort_thread_count_persists(tmp_path):
    path = tmp_path / "settings.json"
    AppSettings(ort_intra_op_threads=6).save(path)

    settings, warnings = AppSettings.load(path)

    assert warnings == []
    assert settings.ort_intra_op_threads == 6
    assert settings.to_config().ort_intra_op_threads == 6


def test_migration_without_schema_keeps_file(tmp_path):
    path = tmp_path / "settings.json"
    raw = {
        "ui_scale": 999,
        "theme": "dark",
        "llm_base_url": "http://box/v1",
        "min_font_size": 1,
        "max_font_size": 9999,
        "future_field": True,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    settings, warnings = AppSettings.load(path)
    assert settings.ui_scale == 150
    assert settings.theme == "dark"
    assert settings.llm_base_url == "http://box/v1"
    assert 8 <= settings.min_font_size <= settings.max_font_size <= 256
    assert warnings
    assert json.loads(path.read_text(encoding="utf-8"))["ui_scale"] == 999


def test_utf8_bom_settings_is_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema": 1, "theme": "dark"}), encoding="utf-8-sig")
    settings, warnings = AppSettings.load(path)
    assert warnings == []
    assert settings.theme == "dark"


def test_newer_schema_reads_known_fields(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"schema": 5, "theme": "light", "not_a_field": 1}),
        encoding="utf-8",
    )
    settings, warnings = AppSettings.load(path)
    assert settings.theme == "light"
    assert warnings
    assert path.is_file()


def test_broken_json_is_renamed_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    raw = "{not json"
    path.write_text(raw, encoding="utf-8")
    settings, warnings = AppSettings.load(path)
    assert settings.theme == "system"
    assert settings.llm_base_url == ""
    assert not path.exists()
    bad = Path(str(path) + ".bad")
    assert bad.read_text(encoding="utf-8") == raw
    assert warnings
    path.write_text("still {", encoding="utf-8")
    AppSettings.load(path)
    assert bad.read_text(encoding="utf-8") == raw
    assert Path(str(path) + ".bad-2").read_text(encoding="utf-8") == "still {"
    assert not path.exists()


def test_save_roundtrip_has_schema_without_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    bag = {}
    module = types.ModuleType("keyring")

    def get_password(service, username):
        assert service == "ImageLocalizationTool"
        assert username == "llm"
        return bag.get((service, username))

    def set_password(service, username, value):
        bag[(service, username)] = value

    def delete_password(service, username):
        bag.pop((service, username), None)

    module.get_password = get_password
    module.set_password = set_password
    module.delete_password = delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)

    settings = AppSettings(theme="dark", llm_base_url="")
    assert settings.set_api_key("secret") is True
    assert settings.get_api_key() == "secret"
    key_file = tmp_path / "data" / "llm-api-key.txt"
    assert key_file.read_text(encoding="utf-8").strip() == "secret"
    assert bag == {}
    config = settings.to_config()
    assert config.llm_api_key == "secret"
    path = tmp_path / "settings.json"
    settings.save(path)
    text = path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "api_key" not in text
    payload = json.loads(text)
    assert payload["schema"] == 1
    assert payload["llm_base_url"] == ""
    assert payload["theme"] == "dark"
    loaded, warnings = AppSettings.load(path)
    assert warnings == []
    assert loaded.theme == "dark"
    assert loaded.llm_base_url == ""
    assert settings.set_api_key("") is True
    assert not key_file.exists()
    assert get_api_key() == ""


def test_key_is_imported_from_keyring_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    bag = {("ImageLocalizationTool", "llm"): "legacy-secret"}
    module = types.ModuleType("keyring")
    module.get_password = lambda service, username: bag.get((service, username))
    module.set_password = lambda service, username, value: bag.__setitem__((service, username), value)
    module.delete_password = lambda service, username: bag.pop((service, username), None)
    monkeypatch.setitem(sys.modules, "keyring", module)

    assert get_api_key() == ""
    assert bag
    assert migrate_legacy_api_key() is True
    key_file = tmp_path / "data" / "llm-api-key.txt"
    assert key_file.read_text(encoding="utf-8").strip() == "legacy-secret"
    assert bag == {}
    assert migrate_legacy_api_key() is True


def test_failed_migration_keeps_keyring(tmp_path, monkeypatch):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv("ILT_DATA_DIR", str(blocker))
    bag = {("ImageLocalizationTool", "llm"): "legacy-secret"}
    module = types.ModuleType("keyring")
    module.get_password = lambda service, username: bag.get((service, username))
    module.set_password = lambda service, username, value: bag.__setitem__((service, username), value)
    module.delete_password = lambda service, username: bag.pop((service, username), None)
    monkeypatch.setitem(sys.modules, "keyring", module)

    assert migrate_legacy_api_key() is False
    assert bag == {("ImageLocalizationTool", "llm"): "legacy-secret"}
    assert "keyring" in migration_warning()
    assert "legacy-secret" not in migration_warning()


def test_keyring_errors_are_soft(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    module = types.ModuleType("keyring")

    def boom(*_args, **_kwargs):
        raise RuntimeError("no keyring")

    module.get_password = boom
    module.set_password = boom
    module.delete_password = boom
    monkeypatch.setitem(sys.modules, "keyring", module)
    assert get_api_key() == ""
    assert migrate_legacy_api_key() is True
    assert set_api_key("x") is True
    assert get_api_key() == "x"
    assert set_api_key("") is True
    assert AppSettings().get_api_key() == ""
    assert AppSettings().set_api_key("x") is True
    assert AppSettings().get_api_key() == "x"
    assert AppSettings().set_api_key("") is True


def test_key_file_is_private_on_posix(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows не поддерживает POSIX-права")
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    assert set_api_key("secret") is True
    mode = stat.S_IMODE((tmp_path / "data" / "llm-api-key.txt").stat().st_mode)
    assert mode == 0o600


def test_appdata_paths_are_cleared_from_settings(tmp_path, monkeypatch):
    local = tmp_path / "local"
    roaming = tmp_path / "roam"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    keep = tmp_path / "custom"

    settings = AppSettings(
        components_dir=str(local / "ImageLocalizationTool" / "components"),
        models_dir=str(roaming / "ImageLocalizationTool" / "models"),
        components_previous_dir=str(keep),
    )

    assert settings.components_dir == ""
    assert settings.models_dir == ""
    assert settings.components_previous_dir == str(keep)


def test_paths_override_does_not_create_directories(tmp_path):
    root = tmp_path / "box"
    paths = AppPaths(root=root, portable=True)
    assert settings_path(paths) == root / "settings.json"
    assert projects_dir(paths) == root / "projects"
    assert logs_dir(paths) == root / "logs"
    assert is_portable(paths) is True
    assert not root.exists()

    local = tmp_path / "local"
    roaming = tmp_path / "roam"
    split = AppPaths(root=local, portable=False, settings_root=roaming)
    assert settings_path(split) == roaming / "settings.json"
    assert projects_dir(split) == local / "projects"
    assert is_portable(split) is False

    with using_paths(paths):
        assert data_root() == root
        assert settings_path(split) == roaming / "settings.json"
    assert data_root() != root


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.paths.install_root", lambda: tmp_path)
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "custom"))
    assert is_portable() is True
    assert data_root() == tmp_path / "custom"
    assert settings_path() == tmp_path / "custom" / "settings.json"
    assert not (tmp_path / "custom").exists()


def test_data_root_always_lives_in_app_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("ILT_DATA_DIR", raising=False)
    monkeypatch.setattr("src.app.paths.install_root", lambda: tmp_path / "app")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    data = tmp_path / "app" / "data"

    assert is_portable() is True
    assert data_root() == data
    assert settings_path() == data / "settings.json"
    assert projects_dir() == data / "projects"
    assert logs_dir() == data / "logs"
    assert not data.exists()

    data.mkdir(parents=True)
    assert data_root() == data


def test_ensure_data_root_creates_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("ILT_DATA_DIR", str(tmp_path / "data"))
    assert ensure_data_root() == tmp_path / "data"
    assert (tmp_path / "data").is_dir()


def test_ensure_data_root_reports_unwritable_location(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")
    with using_paths(AppPaths(root=blocker, portable=True)):
        with pytest.raises(RuntimeError, match="недоступна для записи"):
            ensure_data_root()
