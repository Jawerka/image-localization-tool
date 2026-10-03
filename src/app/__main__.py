import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()

# В оконной сборке stdout и stderr равны None. Подмена — до тяжёлых импортов,
# иначе первый print или логгер роняет процесс. Каталог лога создаёт запуск.

import threading
from pathlib import Path


class _LogStream:
    """Поток с write/flush: пишет в файл лога, когда консоли нет."""

    ilt_log_stream = True

    def __init__(self, path: Path):
        self._path = Path(path)
        self._file = None
        self._lock = threading.Lock()

    def write(self, data) -> int:
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(data)
        if not text:
            return 0
        with self._lock:
            self._open()
            self._file.write(text)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("это не файловый дескриптор")

    def close(self) -> None:
        with self._lock:
            if self._file is None:
                return
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def _open(self) -> None:
        if self._file is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a", encoding="utf-8")


def install_null_stdio(log_path: Path | None = None) -> None:
    """Если stdout или stderr равны None, направить их в файл лога."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    path = log_path
    if path is None:
        from src.app.paths import logs_dir

        folder = logs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "app.log"
    if sys.stdout is None and sys.stderr is None:
        stream = _LogStream(path)
        sys.stdout = stream
        sys.stderr = stream
        return
    if sys.stdout is None:
        sys.stdout = _LogStream(path)
    if sys.stderr is None:
        sys.stderr = _LogStream(path)


def prepare_logging() -> Path:
    """Каталог лога и ротация ``app.log``. Вызывать до импорта окна и воркера."""
    from src.app.paths import logs_dir
    from src.utils.logger import enable_file_logging

    folder = logs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "app.log"
    install_null_stdio(path)
    enable_file_logging(path, rotate=True)
    return path


def _guard_stdio() -> None:
    if sys.stdout is None or sys.stderr is None:
        install_null_stdio()


_guard_stdio()


def main(argv: list[str] | None = None) -> int:
    prepare_logging()
    from src.utils.logger import logger

    logger.info("Запуск приложения")
    from src.app.desktop import launch

    return launch(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
