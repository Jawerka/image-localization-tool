"""Выход дочернего процесса, когда родитель уже умер.

Логика как у sidecar-watchdog: на Windows ожидание хендла процесса,
иначе опрос. Поток не запускается при импорте.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Callable

logger = logging.getLogger("image_localization")

_INFINITE = 0xFFFFFFFF
_SYNCHRONIZE = 0x00100000


def wait_for_parent(pid: int, *, poll_interval: float = 0.5) -> None:
    """Блокироваться, пока процесс ``pid`` жив. Вернуться, когда он завершился."""
    if pid <= 0:
        _wait_stdin_eof()
        return
    if sys.platform == "win32":
        if _wait_windows_process(pid):
            return
        logger.warning("OpenProcess(%s) не удался, дальше опрос", pid)
    while True:
        if not _pid_alive(pid):
            return
        time.sleep(max(0.05, poll_interval))


def _wait_windows_process(pid: int) -> bool:
    try:
        import ctypes
    except ImportError:
        return False
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        kernel32.WaitForSingleObject(handle, _INFINITE)
        return True
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_stdin_eof() -> None:
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return
    try:
        stdin.read()
    except Exception:
        return


def start_parent_watch(
    pid: int,
    *,
    on_parent_gone: Callable[[], None] | None = None,
) -> threading.Thread:
    """Фоновый поток: после смерти родителя вызвать ``on_parent_gone`` или ``os._exit``."""

    def _run() -> None:
        try:
            wait_for_parent(pid)
        except Exception as exc:
            logger.debug("Наблюдение за родителем не удалось: %s", exc)
            return
        logger.info("Родительский процесс %s завершился, воркер выходит", pid)
        if on_parent_gone is not None:
            on_parent_gone()
            return
        os._exit(0)

    thread = threading.Thread(target=_run, name="ilt-parent-watch", daemon=True)
    thread.start()
    return thread
