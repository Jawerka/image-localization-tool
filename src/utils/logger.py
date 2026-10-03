"""Логирование приложения."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FILE_HANDLER = "_ilt_file_handler"


def _formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _console_stream():
    """stderr, иначе stdout. В оконной сборке оба могут быть None."""
    if sys.stderr is not None:
        return sys.stderr
    return sys.stdout


def _attach_file_handler(
    target: logging.Logger,
    path: str | Path,
    *,
    rotate: bool,
    max_bytes: int,
    backup_count: int,
) -> None:
    for handler in list(target.handlers):
        if getattr(handler, _FILE_HANDLER, False):
            target.removeHandler(handler)
            handler.close()
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if rotate:
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_formatter())
    setattr(file_handler, _FILE_HANDLER, True)
    target.addHandler(file_handler)


def setup_logger(name: str = "image_localization", log_file: str | None = "app.log") -> logging.Logger:
    """Настроить логгер. Файл создаётся только если передан log_file."""

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Очистить существующие обработчики
    logger.handlers.clear()

    formatter = _formatter()

    # Консоль (INFO и выше). В оконной сборке потоков может не быть.
    stream = _console_stream()
    if stream is not None:
        console_handler = logging.StreamHandler(stream)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        _attach_file_handler(
            logger,
            log_file,
            rotate=False,
            max_bytes=2_000_000,
            backup_count=3,
        )

    return logger


def enable_file_logging(
    path: str | Path,
    *,
    rotate: bool = False,
    max_bytes: int = 2_000_000,
    backup_count: int = 3,
) -> None:
    """Писать лог в файл. Повторный вызов заменяет прежний файловый обработчик."""
    _attach_file_handler(
        logger,
        path,
        rotate=rotate,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


# Глобальный логгер: только консоль, файл включает точка входа.
logger = setup_logger(log_file=None)
