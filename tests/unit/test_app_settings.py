"""Настройки приложения: кламп, миграция, keyring и пустой адрес LLM."""

import json
import sys
import types
from pathlib import Path

from src.app.paths import (
    AppPaths,
    data_root,
    is_portable,
    logs_dir,
    projects_dir,
    settings_path,
    using_paths,
)
from src.app.settings import AppSettings, get_api_key, set_api_key
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
    assert get_api_key() == ""


def test_keyring_errors_are_soft(monkeypatch):
    module = types.ModuleType("keyring")

    def boom(*_args, **_kwargs):
        raise RuntimeError("no keyring")

    module.get_password = boom
    module.set_password = boom
    module.delete_password = boom
    monkeypatch.setitem(sys.modules, "keyring", module)
    assert get_api_key() == ""
    assert set_api_key("x") is False
    assert AppSettings().get_api_key() == ""
    assert AppSettings().set_api_key("x") is False


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


def test_portable_and_platform_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.paths.install_root", lambda: tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    assert is_portable() is True
    assert data_root() == data
    assert settings_path() == data / "settings.json"
    assert projects_dir() == data / "projects"
    assert logs_dir() == data / "logs"
    assert not (data / "projects").exists()

    data.rmdir()
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("src.app.paths.sys.platform", "win32")
    assert is_portable() is False
    assert settings_path() == tmp_path / "roam" / "ImageLocalizationTool" / "settings.json"
    assert projects_dir() == tmp_path / "local" / "ImageLocalizationTool" / "projects"
    assert logs_dir() == tmp_path / "local" / "ImageLocalizationTool" / "logs"

    home = tmp_path / "home"
    monkeypatch.setattr("src.app.paths.sys.platform", "linux")
    monkeypatch.setattr("src.app.paths.Path.home", lambda: home)
    assert data_root() == home / ".image-localization-tool"
    assert settings_path() == home / ".image-localization-tool" / "settings.json"
    assert is_portable() is False
