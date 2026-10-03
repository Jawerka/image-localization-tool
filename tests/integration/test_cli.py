"""Тесты CLI."""

import pytest

from src.main import build_parser, main


class TestCLI:
    def test_parser_defaults(self):
        args = build_parser().parse_args(["input.png"])
        assert args.input == "input.png"
        assert args.target_lang == "ru"
        assert args.source_lang is None
        assert args.ocr is None

    def test_parser_v2_flags(self):
        args = build_parser().parse_args(
            ["input.png", "--ocr", "rapid", "--translator", "argos", "--source-lang", "en"]
        )
        assert args.ocr == "rapid"
        assert args.translator == "argos"
        assert args.source_lang == "en"

    def test_missing_input_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        code = main(["nonexistent.png"])
        assert code == 1

    def test_help_does_not_crash(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["--help"])
        assert exc.value.code == 0
