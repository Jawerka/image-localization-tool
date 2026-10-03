"""Окно pywebview, нативные диалоги и один экземпляр приложения.

``webview`` импортируется только при старте окна. Запись ``instance.json``,
приём строки с путями и решение «первый / второй» работают без окна.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

from src.app.dialogs import DialogBridge
from src.app.events import JOB_CANCELLED, JOB_FINISHED
from src.app.paths import data_root, logs_dir, settings_path
from src.app.server import AppState, _bootstrap, serve
from src.app.settings import AppSettings

logger = logging.getLogger("image_localization.desktop")

TITLE = "Image Localization Tool"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
MIN_SIZE = (1100, 700)
INSTANCE_FILENAME = "instance.json"
_IMAGE_FILTER = ("Изображения (*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff)",)
_WEBVIEW2_TEXT = (
    "Не удалось открыть окно: не найден WebView2 Runtime.\n\n"
    "Установите Microsoft Edge WebView2 Runtime и запустите программу снова."
)
_CLOSE_TEXT = "Идёт обработка. Закрыть приложение?"
_HEADLESS_IDLE = (
    "Удалённый доступ выключен. Запустите: python -m src.app --headless --remote"
)
HEADLESS_LOCAL_PORT = 8766
SESSION_TOKEN_NAME = "session.token"
_LINE_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class LaunchArgs:
    """Разобранные аргументы запуска."""

    browser: bool
    paths: list[str]
    headless: bool = False
    remote: bool = False


@dataclass(frozen=True)
class InstanceInfo:
    """Живой экземпляр: pid и порт короткого TCP на 127.0.0.1."""

    pid: int
    port: int


def parse_args(argv: list[str]) -> LaunchArgs:
    """Пути, ``--browser``, ``--headless`` и ``--remote``."""
    parser = argparse.ArgumentParser(prog="python -m src.app")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Сервер без окна: открыть системный браузер",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Без окна WebView и без локального интерфейса",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Слушать удалённый LAN API (с --headless — только он)",
    )
    parser.add_argument("paths", nargs="*", help="Файлы и папки страниц")
    # Флаг может стоять и после путей: page.png --browser folder.
    parsed = parser.parse_intermixed_args(list(argv))
    return LaunchArgs(
        browser=bool(parsed.browser),
        paths=[str(item) for item in parsed.paths],
        headless=bool(parsed.headless),
        remote=bool(parsed.remote),
    )


def instance_path(root: Path) -> Path:
    """``instance.json`` в корне данных, не рядом с файлом лога."""
    return Path(root) / INSTANCE_FILENAME


def write_instance(path: Path, pid: int, port: int) -> None:
    """Записать pid и порт TCP. Временный файл заменяется целиком."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": int(pid), "port": int(port)}, ensure_ascii=False) + "\n"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)


def read_instance(path: Path) -> InstanceInfo | None:
    """Прочитать запись. Битый файл — как будто экземпляра нет."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        pid = int(data["pid"])
        port = int(data["port"])
    except (KeyError, TypeError, ValueError):
        return None
    if isinstance(data["pid"], bool) or isinstance(data["port"], bool):
        return None
    if pid <= 0 or port <= 0 or port > 65535:
        return None
    return InstanceInfo(pid=pid, port=port)


def remove_instance(path: Path, pid: int) -> None:
    """Удалить файл, только если в нём наш pid."""
    record = read_instance(path)
    if record is None or record.pid != int(pid):
        return
    try:
        Path(path).unlink()
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """Жив ли процесс.

    На Windows ``os.kill(pid, 0)`` не проверяет процесс, а завершает его.
    """
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if isinstance(pid, bool) or number <= 0 or number > 0xFFFFFFFF:
        return False
    if sys.platform == "win32":
        return _win_pid_alive(number)
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _win_pid_alive(pid: int) -> bool:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED — процесс есть
    kernel32.CloseHandle(handle)
    return True


_kernel32_lib = None


def _kernel32():
    global _kernel32_lib
    if _kernel32_lib is None:
        library = ctypes.WinDLL("kernel32", use_last_error=True)
        library.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        library.OpenProcess.restype = ctypes.c_void_p
        library.CloseHandle.argtypes = (ctypes.c_void_p,)
        library.CloseHandle.restype = ctypes.c_int
        _kernel32_lib = library
    return _kernel32_lib


def parse_paths_message(line: str) -> list[str]:
    """Одна строка JSON ``{"paths": ["..."]}``."""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("Ожидался объект")
    raw = data.get("paths")
    if not isinstance(raw, list):
        raise ValueError("Нужен список paths")
    paths: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("Путь должен быть строкой")
        paths.append(item)
    return paths


def encode_paths_message(paths: list[str]) -> bytes:
    text = json.dumps({"paths": list(paths)}, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def decide_role(record: InstanceInfo | None, *, alive: bool, connected: bool) -> str:
    """``second``, если экземпляр жив и соединение удалось. Иначе ``first``."""
    if record is None or not alive or not connected:
        return "first"
    return "second"


def read_socket_line(conn: socket.socket, limit: int = _LINE_LIMIT) -> str:
    """Прочитать одну строку. Соединение после неё можно закрыть."""
    chunks = bytearray()
    while len(chunks) <= limit:
        piece = conn.recv(4096)
        if not piece:
            break
        chunks.extend(piece)
        if b"\n" in chunks:
            break
    if len(chunks) > limit:
        raise ValueError("Слишком длинное сообщение")
    line, _, _rest = bytes(chunks).partition(b"\n")
    return line.decode("utf-8")


def send_paths(port: int, paths: list[str], timeout: float = 2.0) -> None:
    """Отдать пути первому экземпляру одной строкой JSON."""
    payload = encode_paths_message(paths)
    with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(payload)


def forward_to_running(root: Path, paths: list[str]) -> bool:
    """True — мы второй экземпляр и пути уже отданы. Иначе нужно поднимать сервер."""
    record = read_instance(instance_path(root))
    alive = record is not None and pid_alive(record.pid)
    connected = False
    if alive and record is not None:
        _allow_foreground(record.pid)
        try:
            send_paths(record.port, paths)
            connected = True
        except OSError:
            connected = False
    return decide_role(record, alive=alive, connected=connected) == "second"


class InstanceEndpoint:
    """Слушает 127.0.0.1 и принимает по одной строке JSON за соединение."""

    def __init__(self, root: Path, on_paths: Callable[[list[str]], None], pid: int | None = None):
        self.root = Path(root)
        self._on_paths = on_paths
        self.pid = os.getpid() if pid is None else int(pid)
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def path(self) -> Path:
        return instance_path(self.root)

    def start(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            sock.listen(8)
            sock.settimeout(0.2)
            port = int(sock.getsockname()[1])
            write_instance(self.path, self.pid, port)
        except Exception:
            sock.close()
            raise
        self._server = sock
        self._thread = threading.Thread(target=self._serve, name="ilt-instance", daemon=True)
        self._thread.start()
        return port

    def close(self) -> None:
        self._stop.set()
        sock = self._server
        self._server = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1)
        remove_instance(self.path, self.pid)

    def _serve(self) -> None:
        sock = self._server
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2)
            paths = parse_paths_message(read_socket_line(conn))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Сообщение второго экземпляра отклонено: %s", exc)
            return
        try:
            self._on_paths(paths)
        except Exception:
            logger.exception("Не удалось принять пути второго экземпляра")


class PathInbox:
    """Пути второго запуска, пришедшие до готовности HTTP."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[list[str]] = []
        self._handler: Callable[[list[str]], None] | None = None

    def push(self, paths: list[str]) -> None:
        with self._lock:
            handler = self._handler
            if handler is None:
                self._pending.append(list(paths))
                return
        handler(paths)

    def bind(self, handler: Callable[[list[str]], None]) -> None:
        with self._lock:
            queued = self._pending
            self._pending = []
            self._handler = handler
        for batch in queued:
            handler(batch)


def closing_allowed(busy: bool, confirmed: bool) -> bool:
    """Занятое окно закрывается только после согласия. Простое закрывается сразу."""
    if busy:
        return bool(confirmed)
    return True


def window_kwargs(settings: AppSettings) -> dict:
    """Размер из настроек, иначе 1280×800. Координаты — только если заданы."""
    options: dict = {
        "width": settings.window_width or DEFAULT_WIDTH,
        "height": settings.window_height or DEFAULT_HEIGHT,
        "min_size": MIN_SIZE,
        "zoomable": False,
    }
    if settings.window_x is not None:
        options["x"] = settings.window_x
    if settings.window_y is not None:
        options["y"] = settings.window_y
    return options


def page_url(port: int, token: str) -> str:
    return f"http://127.0.0.1:{int(port)}/?k={token}"


def hwnd_from_native(native) -> int | None:
    """HWND из ``window.native``. Нет дескриптора — None, без исключения."""
    if native is None or isinstance(native, bool):
        return None
    if isinstance(native, int):
        return native or None
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    converter = getattr(handle, "ToInt64", None)
    if converter is None:
        converter = getattr(handle, "ToInt32", None)
    try:
        value = int(converter()) if callable(converter) else int(handle)
    except (TypeError, ValueError, OverflowError):
        return None
    return value or None


def focus_window(window) -> None:
    """Вывести окно вперёд. Нет HWND — ничего не делать."""
    if window is None or sys.platform != "win32":
        return
    restore = getattr(window, "restore", None)
    if getattr(window, "minimized", False) and callable(restore):
        try:
            restore()
        except Exception:
            logger.debug("Окно не развернулось", exc_info=True)
    hwnd = hwnd_from_native(getattr(window, "native", None))
    if not hwnd:
        return
    try:
        _set_foreground(hwnd)
    except Exception:
        logger.debug("Не удалось вывести окно вперёд", exc_info=True)


def _set_foreground(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    try:
        iconic = user32.IsIconic
        _set_argtypes(iconic, [ctypes.c_void_p], ctypes.c_int)
        if iconic(hwnd):
            show = user32.ShowWindow
            _set_argtypes(show, [ctypes.c_void_p, ctypes.c_int], ctypes.c_int)
            show(hwnd, 9)  # SW_RESTORE
    except Exception:
        logger.debug("Окно не развернулось", exc_info=True)
    foreground = user32.SetForegroundWindow
    _set_argtypes(foreground, [ctypes.c_void_p], ctypes.c_int)
    foreground(hwnd)


def _allow_foreground(pid: int) -> None:
    """Второй запуск — передний план и может разрешить фокус первому."""
    if sys.platform != "win32":
        return
    try:
        allow = ctypes.windll.user32.AllowSetForegroundWindow
        _set_argtypes(allow, [ctypes.c_uint32], ctypes.c_int)
        allow(int(pid))
    except Exception:
        logger.debug("AllowSetForegroundWindow не удался", exc_info=True)


def _set_argtypes(fn, argtypes, restype) -> None:
    try:
        fn.argtypes = argtypes
        fn.restype = restype
    except (AttributeError, TypeError):
        pass


def _webview2_installed() -> bool:
    """Есть ли WebView2 Runtime. Без него pywebview молча открывает старый MSHTML."""
    if sys.platform != "win32":
        return True
    import winreg

    guids = (
        "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
        "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",
        "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",
    )
    tails = (
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}",
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
    )
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        for guid in guids:
            for tail in tails:
                try:
                    with winreg.OpenKey(root, tail.format(guid=guid)) as key:
                        build, _kind = winreg.QueryValueEx(key, "pv")
                except OSError:
                    continue
                if _webview2_version_ok(str(build or "")):
                    return True
    return False


def _webview2_version_ok(text: str) -> bool:
    parts = text.strip().split(".")
    numbers: list[int] = []
    for part in parts:
        try:
            numbers.append(int(part))
        except ValueError:
            return False
    return bool(numbers) and numbers[0] > 0


def alert_webview2_missing() -> None:
    """Системное окно: без WebView2 Runtime окно не открыть."""
    if sys.platform != "win32":
        return
    ctypes.windll.user32.MessageBoxW(0, _WEBVIEW2_TEXT, TITLE, 0x00000010)


def run_webview(start: Callable[[], None]) -> int:
    """Запустить окно. Исключение старта — сообщение про WebView2 и код 1."""
    try:
        start()
    except Exception:
        logger.exception("Не удалось запустить окно")
        alert_webview2_missing()
        return 1
    return 0


def bootstrap_busy(state: AppState) -> bool:
    """Флаг ``busy`` из ответа bootstrap. Сбой проверки не блокирует закрытие."""
    try:
        return bool(_bootstrap(state).get("busy"))
    except Exception:
        logger.exception("Не удалось проверить, идёт ли обработка")
        return False


def post_drop(port: int, token: str, paths: list[str]) -> int:
    """``POST /api/drop`` на свой HTTP с cookie сессии и Host 127.0.0.1."""
    if not paths:
        return 0
    body = json.dumps({"paths": list(paths)}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Host": f"127.0.0.1:{int(port)}",
        "Cookie": f"ilt_session={token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    last_error: Exception | None = None
    for _attempt in range(40):
        try:
            conn = HTTPConnection("127.0.0.1", int(port), timeout=5)
            try:
                conn.request("POST", "/api/drop", body=body, headers=headers)
                response = conn.getresponse()
                response.read()
                status = int(response.status)
            finally:
                conn.close()
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
            continue
        if status >= 500:
            time.sleep(0.05)
            continue
        if status >= 400:
            logger.warning("Пути не добавлены, ответ %s", status)
        return status
    logger.error("Не удалось отправить пути: %s", last_error)
    return 0


def reveal_path(path: Path) -> None:
    """На Windows выделить файл в проводнике или открыть папку."""
    target = Path(path)
    if sys.platform != "win32":
        logger.info("Показать путь: %s", target)
        return
    try:
        if target.is_file():
            subprocess.Popen(f'explorer /select,"{target}"')
            return
        folder = target if target.is_dir() else target.parent
        os.startfile(os.fspath(folder))  # type: ignore[attr-defined]
    except OSError:
        logger.exception("Не удалось открыть %s", target)


def _dialog_paths(chosen) -> list[Path]:
    if not chosen:
        return []
    if isinstance(chosen, (str, Path)):
        return [Path(chosen)]
    return [Path(item) for item in chosen]


class WebViewDialogs(DialogBridge):
    """Диалоги pywebview. Окно подставляется, когда оно уже создано."""

    def __init__(self, log_path: Path | None = None):
        self.window = None
        self.log_path = Path(log_path) if log_path is not None else logs_dir() / "app.log"

    def open_files(self) -> list[Path]:
        window = self.window
        if window is None:
            return []
        import webview

        chosen = window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=_IMAGE_FILTER,
        )
        return _dialog_paths(chosen)

    def open_folder(self) -> Path | None:
        return self._pick_folder()

    def pick_directory(self) -> Path | None:
        return self._pick_folder()

    def reveal(self, path: Path) -> None:
        reveal_path(Path(path))

    def open_log(self) -> None:
        reveal_path(self.log_path)

    def _pick_folder(self) -> Path | None:
        window = self.window
        if window is None:
            return None
        import webview

        chosen = _dialog_paths(window.create_file_dialog(webview.FOLDER_DIALOG))
        if not chosen:
            return None
        return chosen[0]


def _build_server(dialogs: DialogBridge, *, port: int = 0) -> tuple[AppState, object]:
    """Сервер и очередь. Процесс воркера стартует только с первым заданием."""
    from src.app.jobs import JobQueue
    from src.app.store import ProjectStore
    from src.app.worker import ProcessWorker

    file_path = settings_path()
    settings, warnings = AppSettings.load(file_path)
    state = AppState(
        settings=settings,
        settings_path=file_path,
        store=ProjectStore(data_root()),
        queue=JobQueue(ProcessWorker()),
        dialogs=dialogs,
        settings_warnings=warnings,
    )
    httpd, _port = serve(state, port=port)
    return state, httpd


def _write_session_token(token: str) -> Path:
    """Записать токен сессии рядом с данными (режим 0600, где ОС это поддерживает)."""
    path = data_root() / SESSION_TOKEN_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(token or ""), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _payload_remote_id(job) -> str:
    payload = job.get("payload") if isinstance(job, dict) else getattr(job, "payload", None)
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("remote_job_id") or "")


def _event_page(job, event) -> tuple[str, str]:
    if isinstance(job, dict):
        project_id = str(job.get("project_id") or "")
        page_id = str(job.get("page_id") or "")
    else:
        project_id = str(getattr(job, "project_id", "") or "")
        page_id = str(getattr(job, "page_id", "") or "")
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return project_id, page_id
    return (
        str(payload.get("project_id") or project_id),
        str(payload.get("page_id") or page_id),
    )


def _remote_failure(event) -> str:
    if getattr(event, "type", "") == JOB_CANCELLED:
        return "Задание отменено"
    payload = getattr(event, "payload", None)
    if isinstance(payload, dict):
        text = str(payload.get("error") or "").strip()
        if text:
            return text
    return "Ошибка перевода"


class DesktopApp:
    """Сервер в фоновом потоке, окно — в главном."""

    def __init__(self, state: AppState, httpd, endpoint: InstanceEndpoint):
        self.state = state
        self.httpd = httpd
        self.endpoint = endpoint
        self.window = None
        self.remote_api = None
        self._remote_lock = threading.Lock()
        self._remote_slots: dict[str, dict] = {}
        self._remote_hook = None
        self._remote_progress_hook = None
        self._stopped = False
        self._http_started = False
        self.state.remote_api = None

    @classmethod
    def open(
        cls,
        *,
        browser: bool,
        endpoint: InstanceEndpoint,
        remote: bool = False,
    ) -> DesktopApp:
        if browser:
            dialogs: DialogBridge = DialogBridge()
        else:
            dialogs = WebViewDialogs(logs_dir() / "app.log")
        state, httpd = _build_server(dialogs)
        app = cls(state, httpd, endpoint)
        app.start_remote(force=remote)
        return app

    def start_remote(self, *, force: bool) -> None:
        """Поднять LAN-слушатель, если он включён. Локальный UI остаётся на 127.0.0.1."""
        settings = self.state.settings
        if force:
            settings.remote_enabled = True
        if not settings.remote_enabled:
            return
        from src.app.remote import RemoteServer

        server = RemoteServer(
            settings,
            settings_path=self.state.settings_path,
            store=self.state.store,
        )
        try:
            port = server.start(settings.remote_bind, settings.remote_port)
        except OSError:
            logger.exception(
                "Удалённый API не запустился на %s:%s",
                settings.remote_bind,
                settings.remote_port,
            )
            return
        self.remote_api = server
        self.state.remote_api = server
        self._bind_remote_runner(server)
        logger.info("Удалённый API http://%s:%s", settings.remote_bind, port)

    def _bind_remote_runner(self, server) -> None:
        """Поставить раннер там, где видны и очередь, и удалённый сервер.

        Поток HTTP только принимает запрос. Поток ``ilt-remote-job`` ждёт
        хук воркера и не гоняет пайплайн в этом процессе.
        """
        worker = getattr(self.state.queue, "worker", None)
        if worker is not None:
            # Один и тот же объект: повторное чтение метода даёт другой bound method.
            self._remote_hook = self._on_remote_page
            self._remote_progress_hook = self._on_remote_progress
            worker.on_page_done = self._remote_hook
            worker.on_progress = self._remote_progress_hook
        server.set_runner(self._remote_runner)

    def _remote_runner(self, job) -> None:
        """Поставить страницу в очередь. Готовый PNG закроет хук воркера."""
        from src.app.remote_bridge import run_remote_job

        def translate_page(project_id: str, page_id: str) -> bytes:
            if not str(page_id or "").strip():
                raise RuntimeError("нет страницы Входящие")
            return self._wait_remote_page(job, str(project_id or ""), str(page_id))

        run_remote_job(job, translate_page)

    def _wait_remote_page(self, job, project_id: str, page_id: str) -> bytes:
        """Ждать хук на потоке удалённого задания, не на потоке HTTP."""
        slot = {"event": threading.Event(), "png": b"", "error": ""}
        with self._remote_lock:
            self._remote_slots[job.id] = slot
        try:
            settings = self.state.settings.to_dict()
            source = str(getattr(job, "source_lang", "") or "")
            target = str(getattr(job, "target_lang", "") or "")
            if source:
                settings["source_lang"] = source
            if target:
                settings["target_lang"] = target
            self.state.queue.submit(
                "translate_page",
                project_id,
                page_id=page_id,
                settings=settings,
                payload={
                    "page_id": page_id,
                    "skip_ready": False,
                    "remote_job_id": job.id,
                    "store_root": str(self.state.store.root),
                    "source_path": self._remote_source_path(project_id, page_id),
                },
            )
            slot["event"].wait()
        finally:
            with self._remote_lock:
                self._remote_slots.pop(job.id, None)
        if slot["error"]:
            raise RuntimeError(slot["error"])
        png = slot["png"]
        if not png:
            raise RuntimeError("Пустой результат")
        return bytes(png)

    def _on_remote_progress(self, job, event) -> None:
        """Прокинуть этап пайплайна в опрос ``GET /v1/jobs/{id}``."""
        remote_id = _payload_remote_id(job)
        if not remote_id:
            return
        server = self.remote_api
        if server is None:
            return
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            payload = {}
        stage = str(payload.get("stage") or "")
        try:
            progress = int(payload.get("progress") or 0)
        except (TypeError, ValueError):
            progress = 0
        try:
            server.queue.note_progress(remote_id, stage, progress)
        except Exception:
            logger.exception("Прогресс удалённого задания %s не записан", remote_id)

    def _on_remote_page(self, job, event) -> None:
        """Воркер закончил страницу — закрыть связанное удалённое задание."""
        remote_id = _payload_remote_id(job)
        if not remote_id:
            return
        with self._remote_lock:
            slot = self._remote_slots.get(remote_id)
        server = self.remote_api
        if server is None:
            if slot is not None:
                slot["error"] = "Удалённый API остановлен"
                slot["event"].set()
            return
        try:
            if getattr(event, "type", "") == JOB_FINISHED:
                project_id, page_id = _event_page(job, event)
                png = self._read_result_png(project_id, page_id)
                if not png:
                    raise RuntimeError("Пустой результат")
                server.complete(remote_id, png)
                if slot is not None:
                    slot["png"] = png
            else:
                message = _remote_failure(event)
                server.queue.fail(remote_id, message)
                if slot is not None:
                    slot["error"] = message
        except Exception as exc:
            message = str(exc) or "Ошибка перевода"
            if slot is not None and not slot.get("png"):
                slot["error"] = message
            try:
                server.queue.fail(remote_id, message)
            except Exception:
                logger.exception("Удалённое задание %s не закрылось", remote_id)
        finally:
            if slot is not None:
                slot["event"].set()

    def _remote_source_path(self, project_id: str, page_id: str) -> str:
        try:
            project = self.state.store.open_project(project_id)
        except (OSError, ValueError):
            return ""
        for item in project.get("pages") or []:
            if str(item.get("id") or "") == page_id:
                return str(item.get("source_path") or "")
        return ""

    def _read_result_png(self, project_id: str, page_id: str) -> bytes:
        if not project_id or not page_id:
            return b""
        try:
            path = self.state.store.image_path(project_id, page_id, "result")
        except (OSError, ValueError):
            return b""
        if not path.is_file():
            return b""
        try:
            return path.read_bytes()
        except OSError:
            return b""

    def accept_paths(self, paths: list[str]) -> None:
        if paths:
            post_drop(self.state.port, self.state.token, paths)
        focus_window(self.window)

    def bind_window(self, window) -> None:
        self.window = window
        if isinstance(self.state.dialogs, WebViewDialogs):
            self.state.dialogs.window = window

    def on_closing(self) -> bool:
        """False оставляет окно. Геометрия пишется здесь, очередь и HTTP — после цикла окна."""
        busy = bootstrap_busy(self.state)
        confirmed = True
        if busy:
            confirmed = self._ask_close()
        if not closing_allowed(busy, confirmed):
            return False
        self._save_geometry()
        return True

    def run_window(self, paths: list[str], inbox: PathInbox) -> int:
        self._start_http_thread()
        inbox.bind(self.accept_paths)
        if paths:
            post_drop(self.state.port, self.state.token, paths)
        return self._open_window()

    def run_browser(self, paths: list[str], inbox: PathInbox) -> int:
        import webbrowser

        def open_page() -> None:
            inbox.bind(self.accept_paths)
            if paths:
                post_drop(self.state.port, self.state.token, paths)
            webbrowser.open(page_url(self.state.port, self.state.token))

        threading.Thread(target=open_page, name="ilt-browser", daemon=True).start()
        self._http_started = True
        try:
            self.httpd.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            logger.info("Остановка")
        return 0

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        endpoint = self.endpoint
        self.endpoint = None
        if endpoint is not None:
            try:
                endpoint.close()
            except Exception:
                logger.exception("Экземпляр не закрылся")
        try:
            self.state.queue.shutdown()
        except Exception:
            logger.exception("Очередь не остановилась")
        self._stop_remote()
        self._stop_http()

    def _open_window(self) -> int:
        def start() -> None:
            if not _webview2_installed():
                raise RuntimeError("WebView2 Runtime не найден")
            import webview

            window = webview.create_window(
                TITLE,
                page_url(self.state.port, self.state.token),
                **window_kwargs(self.state.settings),
            )
            self.bind_window(window)
            window.events.closing += self.on_closing
            # private_mode: localStorage не нужен, настройки интерфейса в settings.json.
            webview.start(gui="edgechromium", private_mode=True)

        return run_webview(start)

    def _ask_close(self) -> bool:
        window = self.window
        if window is None:
            return False
        try:
            return bool(window.create_confirmation_dialog(TITLE, _CLOSE_TEXT))
        except Exception:
            logger.exception("Не удалось спросить подтверждение закрытия")
            return True

    def _save_geometry(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            settings = self.state.settings
            settings.window_x = int(window.x)
            settings.window_y = int(window.y)
            settings.window_width = int(window.width)
            settings.window_height = int(window.height)
            settings.save(self.state.settings_path)
        except Exception:
            logger.exception("Геометрия окна не сохранилась")

    def _start_http_thread(self) -> None:
        self._http_started = True
        thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="ilt-http",
            daemon=True,
        )
        thread.start()

    def _stop_remote(self) -> None:
        server = self.remote_api
        self.remote_api = None
        self.state.remote_api = None
        worker = getattr(getattr(self.state, "queue", None), "worker", None)
        if worker is not None:
            if getattr(worker, "on_page_done", None) is self._remote_hook:
                worker.on_page_done = None
                self._remote_hook = None
            if getattr(worker, "on_progress", None) is self._remote_progress_hook:
                worker.on_progress = None
                self._remote_progress_hook = None
        with self._remote_lock:
            pending = list(self._remote_slots.values())
            self._remote_slots.clear()
        for slot in pending:
            if not slot.get("png") and not slot.get("error"):
                slot["error"] = "Удалённый API остановлен"
            slot["event"].set()
        if server is None:
            return
        try:
            server.set_runner(None)
        except Exception:
            logger.exception("Раннер удалённого API не снят")
        try:
            server.shutdown()
        except Exception:
            logger.exception("Удалённый API не остановился")

    def _stop_http(self) -> None:
        if self._http_started:
            try:
                self.httpd.shutdown()
            except Exception:
                logger.exception("HTTP-сервер не остановился")
        try:
            self.httpd.server_close()
        except Exception:
            logger.exception("Сокет сервера не закрылся")


def run_headless(args: LaunchArgs) -> int:
    """Без окна. С ``--remote`` — LAN API и пайплайн, локальный UI только на 127.0.0.1.

    Флаг включает удалённый API на этот процесс, даже если в настройках он выключен.
    Локальный HTTP (код сопряжения) слушает ``127.0.0.1`` на ``HEADLESS_LOCAL_PORT``.
    """
    if not args.remote:
        logger.info("Headless без --remote: удалённый API не слушает")
        print(_HEADLESS_IDLE)
        return 0

    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    state, httpd = _build_server(DialogBridge(), port=HEADLESS_LOCAL_PORT)
    for warning in state.settings_warnings:
        logger.warning("%s", warning)
    app = DesktopApp(state, httpd, endpoint=None)
    app.start_remote(force=True)
    if app.remote_api is None:
        print(
            "Не удалось запустить удалённый API на "
            f"{state.settings.remote_bind}:{state.settings.remote_port}"
        )
        app.shutdown()
        return 1

    token_path = _write_session_token(state.token)
    app._start_http_thread()
    remote_port = app.remote_api.port
    local_port = int(state.port)
    logger.info(
        "Удалённый API http://%s:%s, локальный http://127.0.0.1:%s",
        state.settings.remote_bind,
        remote_port,
        local_port,
    )
    print(f"Удалённый API слушает {state.settings.remote_bind}:{remote_port}")
    print(f"Локальный API http://127.0.0.1:{local_port} (токен: {token_path})")
    try:
        app.remote_api.wait()
    except KeyboardInterrupt:
        logger.info("Остановка удалённого API")
    finally:
        app.shutdown()
    return 0


def launch(argv: list[str] | None = None) -> int:
    """Первый экземпляр держит сервер. Второй отдаёт пути и выходит.

    ``--headless`` не открывает окно. Удалённый API в этом режиме — только с ``--remote``.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.headless:
        return run_headless(args)
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    if forward_to_running(root, args.paths):
        logger.info("Пути переданы уже запущенному экземпляру")
        return 0

    inbox = PathInbox()
    endpoint = InstanceEndpoint(root, inbox.push)
    endpoint.start()
    app: DesktopApp | None = None
    try:
        app = DesktopApp.open(browser=args.browser, endpoint=endpoint, remote=args.remote)
        logger.info("Сервер http://127.0.0.1:%s", app.state.port)
        if args.browser:
            return app.run_browser(args.paths, inbox)
        return app.run_window(args.paths, inbox)
    finally:
        if app is not None:
            app.shutdown()
        else:
            endpoint.close()
