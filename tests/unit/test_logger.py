"""Логгер не создаёт файл при импорте и пишет его по запросу."""

import logging
import os
import subprocess
import sys

from src.utils.logger import enable_file_logging, logger, set_console_level
from src.utils.paths import project_root


def _close_file_handlers() -> None:
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()


def test_set_console_level_leaves_file_handler(tmp_path):
    path = tmp_path / "app.log"
    try:
        enable_file_logging(path)
        set_console_level(logging.DEBUG)
        console = [
            handler for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        ]
        files = [handler for handler in logger.handlers if isinstance(handler, logging.FileHandler)]
        assert console and all(handler.level == logging.DEBUG for handler in console)
        assert files and all(handler.level == logging.DEBUG for handler in files)
        set_console_level(logging.INFO)
        assert all(handler.level == logging.INFO for handler in console)
        assert all(handler.level == logging.DEBUG for handler in files)
    finally:
        _close_file_handlers()
        set_console_level(logging.INFO)


def test_import_main_does_not_create_cwd_log(tmp_path):
    env = os.environ.copy()
    root = str(project_root())
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    env["ILT_DATA_DIR"] = str(tmp_path / "data")
    completed = subprocess.run(
        [sys.executable, "-c", "import src.main"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "app.log").exists()
    assert not (tmp_path / "data" / "logs" / "cli.log").exists()


def test_import_does_not_create_log_file(tmp_path):
    env = os.environ.copy()
    root = str(project_root())
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", "import src.utils.logger"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert list(tmp_path.glob("*.log")) == []


def test_enable_file_logging_writes_line(tmp_path):
    path = tmp_path / "logs" / "app.log"
    try:
        enable_file_logging(path)
        enable_file_logging(path)
        logger.info("строка-лога")
        for handler in logger.handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
        assert text.count("строка-лога") == 1
    finally:
        _close_file_handlers()
