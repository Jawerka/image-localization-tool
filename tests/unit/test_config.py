"""Тесты конфигурации."""

import json

from src.config import Config


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.source_lang == "en"
        assert config.target_lang == "ru"
        assert config.llm_base_url == "http://127.0.0.1:8080/v1"
        assert config.ocr_backend == "vlm"
        assert config.sfx_mode == "skip"

    def test_load_missing_file(self, tmp_path):
        config = Config.load(tmp_path / "missing.json")
        assert config.min_confidence == 0.5

    def test_load_valid_file(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"min_confidence": 0.8, "llm_base_url": "http://127.0.0.1:9/v1"}),
            encoding="utf-8",
        )
        config = Config.load(path)
        assert config.min_confidence == 0.8
        assert config.llm_base_url == "http://127.0.0.1:9/v1"

    def test_load_ignores_unknown_fields(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"ocr_engine": "tesseract", "min_confidence": 0.6}),
            encoding="utf-8",
        )
        config = Config.load(path)
        assert config.min_confidence == 0.6
        assert not hasattr(config, "ocr_engine")

    def test_load_invalid_json(self, tmp_path, capsys):
        path = tmp_path / "config.json"
        path.write_text("{invalid", encoding="utf-8")
        config = Config.load(path)
        assert config.min_confidence == 0.5

    def test_save(self, tmp_path):
        config = Config(min_confidence=0.7)
        path = tmp_path / "out.json"
        config.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["min_confidence"] == 0.7
