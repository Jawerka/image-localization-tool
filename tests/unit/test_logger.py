"""Логгер не создаёт файл при импорте и пишет его по запросу."""

import logging
import os
import subprocess
import sys

from src.utils.logger import enable_file_logging, logger
from src.utils.paths import project_root


def _close_file_handlers() -> None:
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()


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
