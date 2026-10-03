"""Удалённый LAN API для расширения браузера.

Слушает отдельно от локального UI (тот остаётся на ``127.0.0.1``).
Цикл — ``ThreadingHTTPServer``. Порт ``0`` в тестах выбирает свободный порт.

Контракт:

* ``GET /v1/health`` → ``{"version": "dev", "ready": true|false}``
* ``POST /v1/pair`` ``{"code": "123456"}`` → ``{"token": "<secret>"}`` или 401
* ``POST /v1/translate`` → всегда **202** ``{"job_id": "..."}``.
  Попадание в кэш не отдаёт PNG в этом ответе: задание сразу ``done``,
  картинка лежит на ``GET /v1/jobs/{id}/result``.
* ``GET /v1/jobs/{id}`` → ``id``, ``status`` (queued|running|done|error),
  ``stage``, ``position``, ``error``
* ``GET /v1/jobs/{id}/result`` → ``image/png``, иначе 409
* ``DELETE /v1/jobs/{id}`` → 204

``ready`` — слушатель принял сокет. Пока воркер не вызвал ``set_runner``,
новые задания остаются ``queued``. Завершение: ``job.finish(png)``
(то же самое, что ``RemoteServer.complete(job_id, png)``).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

from src.app.paths import cache_dir as app_cache_dir
from src.app.remote_auth import (
    Device,
    Pairing,
    RateLimiter,
    find_device,
    make_device,
    remember_hash,
    revoke as drop_device,
)
from src.app.remote_cache import CacheKey, ImageCache, fingerprint_settings
from src.app.settings import AppSettings

logger = logging.getLogger("image_localization.remote")

API_VERSION = "dev"
MAX_BODY_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PENDING = 8
INBOX_NAME = "Входящие"
_LOG_LIMIT = 50

_JOB_RESULT = re.compile(r"^/v1/jobs/([0-9a-fA-F]+)/result$")
_JOB = re.compile(r"^/v1/jobs/([0-9a-fA-F]+)$")
_BOUNDARY = re.compile(r"""boundary\s*=\s*(?:"([^"]+)"|([^;\s]+))""", re.IGNORECASE)
_DISPOSITION_NAME = re.compile(r'name="([^"]*)"')
_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
_ALLOW_METHODS = "GET, POST, DELETE"
_ALLOW_HEADERS = "Authorization, Content-Type, X-Source-Lang, X-Target-Lang"
_TERMINAL = ("done", "error")


class QueueFull(Exception):
    """В очереди уже максимум незавершённых заданий."""


class _HttpError(Exception):
    """Ответ с кодом и JSON ``{"error": ...}``."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = {"error": message}


def body_too_large(size: int, limit: int = MAX_BODY_BYTES) -> bool:
    """True, если размер тела больше лимита. Ровно ``limit`` ещё допустим."""
    if isinstance(size, bool):
        return True
    try:
        number = int(size)
    except (TypeError, ValueError):
        return True
    return number > limit


def pixel_too_large(width: int, height: int, limit: int = MAX_PIXELS) -> bool:
    """True, если ширина или высота меньше нуля либо пикселей больше лимита."""
    if isinstance(width, bool) or isinstance(height, bool):
        return True
    try:
        pixels = int(width) * int(height)
    except (TypeError, ValueError):
        return True
    if width < 0 or height < 0:
        return True
    return pixels > limit


def parse_multipart(body: bytes, content_type: str) -> dict[str, bytes]:
    """Поля ``multipart/form-data``. Одинаковые имена: остаётся последнее."""
    match = _BOUNDARY.search(content_type or "")
    if match is None:
        raise _HttpError(400, "Нет boundary")
    token = match.group(1) if match.group(1) is not None else match.group(2)
    marker = b"--" + token.encode("latin-1")
    fields: dict[str, bytes] = {}
    for chunk in body.split(marker):
        if chunk.startswith(b"--"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        elif chunk.endswith(b"\n"):
            chunk = chunk[:-1]
        if not chunk:
            continue
        header_blob, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            header_blob, separator, data = chunk.partition(b"\n\n")
        if not separator:
            continue
        header = header_blob.decode("latin-1", errors="replace")
        found = _DISPOSITION_NAME.search(header)
        if found is None:
            continue
        fields[found.group(1)] = data
    return fields


def _cors_origin(value: str | None) -> str | None:
    """Origin расширения или None. В заголовок уходит исходная строка."""
    if not value:
        return None
    text = value.strip()
    if not text or any(char in text for char in "\r\n"):
        return None
    lowered = text.lower()
    if lowered.startswith(_ORIGIN_PREFIXES):
        return text
    return None


def _pipeline_fingerprint(settings: AppSettings) -> str:
    """Отпечаток полей, от которых зависит картинка перевода."""
    return fingerprint_settings(
        {
            "ocr_backend": settings.ocr_backend,
            "translator_backend": settings.translator_backend,
            "inpainter_backend": settings.inpainter_backend,
            "llm_base_url": settings.llm_base_url,
            "llm_model": settings.llm_model,
            "llm_thinking": settings.llm_thinking,
            "reading_order": settings.reading_order,
            "translate_sfx": settings.translate_sfx,
            "device": settings.device,
            "glossary_path": settings.glossary_path,
            "detector_conf": settings.detector_conf,
            "text_stroke_ratio": settings.text_stroke_ratio,
            "text_margin": settings.text_margin,
            "min_font_size": settings.min_font_size,
            "max_font_size": settings.max_font_size,
        }
    )


def _image_size(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:
        raise _HttpError(400, "Файл не является изображением") from None


def _field_text(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace").strip()


def _fresh_flag(value: str) -> bool:
    """Поле ``fresh``: заново прогнать пайплайн, не читая кэш результата."""
    return value.strip().lower() in ("1", "true", "yes")


class RemoteJob:
    """Одно входящее изображение. Воркер завершает его через ``finish``."""

    def __init__(
        self,
        *,
        image: bytes,
        source_lang: str,
        target_lang: str,
        device_id: str,
        cache_key: CacheKey,
        job_id: str | None = None,
    ):
        self.id = job_id or uuid.uuid4().hex
        self.image = image
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.device_id = device_id
        self.cache_key = cache_key
        self.status = "queued"
        self.stage = "queued"
        self.progress = 0
        self.error = ""
        self.result: bytes | None = None
        self.project_id = ""
        self.page_id = ""
        self._queue: RemoteQueue | None = None
        self._started = False

    def finish(self, png: bytes) -> None:
        """Положить готовый PNG и перевести задание в ``done``.

        Это хук, который воркер вызывает в конце пайплайна::

            def runner(job: RemoteJob) -> None:
                png = translate(job.image, job.source_lang, job.target_lang)
                job.finish(png)

            server.set_runner(runner)

        ``RemoteServer.complete(job_id, png)`` делает то же самое,
        если на руках только идентификатор.
        """
        queue = self._queue
        if queue is None:
            raise RuntimeError("Задание не в очереди")
        queue.complete(self.id, png)

    def fail(self, message: str) -> None:
        """Перевести задание в ``error``. Повторный вызов после ``done`` игнорируется."""
        queue = self._queue
        if queue is None:
            raise RuntimeError("Задание не в очереди")
        queue.fail(self.id, message)


class RemoteQueue:
    """Очередь удалённых заданий. ``runner(job)`` подменяет пайплайн в тестах."""

    def __init__(
        self,
        runner: Callable[[RemoteJob], None] | None = None,
        *,
        max_pending: int = MAX_PENDING,
        before_done: Callable[[RemoteJob], None] | None = None,
        after_done: Callable[[RemoteJob], None] | None = None,
        on_fail: Callable[[RemoteJob], None] | None = None,
    ):
        self.max_pending = max_pending
        self._runner = runner
        self._before_done = before_done
        self._after_done = after_done
        self._on_fail = on_fail
        self._jobs: dict[str, RemoteJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def set_runner(self, runner: Callable[[RemoteJob], None] | None) -> None:
        """Подключить пайплайн и запустить уже стоящие в очереди задания."""
        with self._lock:
            self._runner = runner
            waiting = [
                self._jobs[job_id]
                for job_id in self._order
                if job_id in self._jobs
                and self._jobs[job_id].status == "queued"
                and not self._jobs[job_id]._started
            ]
        if runner is None:
            return
        for job in waiting:
            self._kick(job)

    def submit(self, job: RemoteJob) -> None:
        """Поставить в очередь. ``QueueFull``, если незавершённых уже ``max_pending``."""
        with self._lock:
            if self._pending() >= self.max_pending:
                raise QueueFull()
            job._queue = self
            job.status = "queued"
            if not job.stage:
                job.stage = "queued"
            self._jobs[job.id] = job
            self._order.append(job.id)
            armed = self._runner is not None
        if armed:
            self._kick(job)

    def remember(self, job: RemoteJob) -> None:
        """Учесть уже готовое задание (попадание в кэш), не занимая слот очереди."""
        with self._lock:
            job._queue = self
            self._jobs[job.id] = job
            self._order.append(job.id)

    def note_progress(self, job_id: str, stage: str, progress: int) -> None:
        """Обновить этап и процент незавершённого задания. После ``done`` и ``error`` — нет."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL:
                return
            text = str(stage or "").strip()
            if text:
                job.stage = text[:80]
            try:
                value = int(progress)
            except (TypeError, ValueError):
                value = 0
            job.progress = max(0, min(100, value))

    def complete(self, job_id: str, png: bytes) -> None:
        """Сохранить PNG, затем выставить ``done``. Пустой результат — это ошибка."""
        if not isinstance(png, (bytes, bytearray)) or not bytes(png):
            self.fail(job_id, "Пустой результат")
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL:
                return
            job.result = bytes(png)
        if self._before_done is not None:
            try:
                self._before_done(job)
            except Exception:
                logger.exception("Результат задания %s не записан в кэш", job_id)
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None or current.status in _TERMINAL:
                return
            current.status = "done"
            current.error = ""
            current.progress = 100
            if current.stage in ("", "queued", "translate"):
                current.stage = "done"
        if self._after_done is not None:
            try:
                self._after_done(job)
            except Exception:
                logger.exception("Страница задания %s не обновлена", job_id)

    def fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL:
                return
            job.status = "error"
            job.stage = "error"
            job.error = str(message or "")[:500]
            failed = job
        if self._on_fail is not None:
            try:
                self._on_fail(failed)
            except Exception:
                logger.exception("Ошибка задания %s не записана на страницу", job_id)

    def view(self, job_id: str, device_id: str) -> dict | None:
        with self._lock:
            job = self._owned(job_id, device_id)
            if job is None:
                return None
            return {
                "id": job.id,
                "status": job.status,
                "stage": job.stage,
                "progress": int(job.progress),
                "position": self._position(job),
                "error": job.error,
            }

    def result_bytes(self, job_id: str, device_id: str) -> tuple[str, bytes | None]:
        """``missing`` / ``wait`` / ``ready`` и PNG, если он уже есть."""
        with self._lock:
            job = self._owned(job_id, device_id)
            if job is None:
                return "missing", None
            if job.status != "done" or not job.result:
                return "wait", None
            return "ready", job.result

    def delete(self, job_id: str, device_id: str) -> bool:
        with self._lock:
            job = self._owned(job_id, device_id)
            if job is None:
                return False
            self._jobs.pop(job_id, None)
            self._order = [item for item in self._order if item != job_id]
            return True

    def _owned(self, job_id: str, device_id: str) -> RemoteJob | None:
        job = self._jobs.get(job_id)
        if job is None or job.device_id != device_id:
            return None
        return job

    def _pending(self) -> int:
        return sum(1 for job in self._jobs.values() if job.status in ("queued", "running"))

    def _position(self, job: RemoteJob) -> int:
        if job.status != "queued":
            return 0
        place = 0
        for job_id in self._order:
            other = self._jobs.get(job_id)
            if other is None or other.status != "queued":
                continue
            place += 1
            if other.id == job.id:
                return place
        return 0

    def _kick(self, job: RemoteJob) -> None:
        with self._lock:
            if self._runner is None or job.status != "queued" or job._started:
                return
            job._started = True
        thread = threading.Thread(
            target=self._run,
            args=(job,),
            name="ilt-remote-job",
            daemon=True,
        )
        thread.start()

    def _run(self, job: RemoteJob) -> None:
        with self._lock:
            if job.status != "queued":
                return
            job.status = "running"
            if job.stage in ("", "queued"):
                job.stage = "translate"
            runner = self._runner
        if runner is None:
            return
        try:
            runner(job)
        except Exception as exc:
            logger.exception("Удалённое задание %s упало", job.id)
            self.fail(job.id, str(exc)[:500] or "Ошибка перевода")
            return
        with self._lock:
            if job.status == "running":
                job.status = "error"
                job.stage = "error"
                job.error = job.error or "Воркер не вернул результат"


class _RemoteHTTP(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, remote: RemoteServer):
        self.remote = remote
        super().__init__(address, handler)


class RemoteServer:
    """Слушатель ``/v1/*``. ``start`` / ``shutdown`` не трогают локальный UI."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        settings_path: Path | str | None = None,
        store=None,
        cache_dir: Path | str | None = None,
        cache: ImageCache | None = None,
        runner: Callable[[RemoteJob], None] | None = None,
        clock: Callable[[], float] | None = None,
        max_pending: int = MAX_PENDING,
    ):
        self.settings = settings
        self.store = store
        self._settings_path = Path(settings_path) if settings_path is not None else None
        self._clock = clock or time.time
        base = Path(cache_dir) if cache_dir is not None else app_cache_dir() / "remote"
        self.inbox_dir = base / "inbox"
        self.cache = cache if cache is not None else ImageCache(base / "results")
        self.pairing = Pairing(clock=self._clock)
        self.limiter = RateLimiter(clock=self._clock)
        self.queue = RemoteQueue(
            runner,
            max_pending=max_pending,
            before_done=self._cache_result,
            after_done=self._sync_page,
            on_fail=self._sync_page,
        )
        self.host = ""
        self.port = 0
        self._listening = False
        self._httpd: _RemoteHTTP | None = None
        self._thread: threading.Thread | None = None
        self._auth_lock = threading.Lock()
        self._io = threading.Lock()
        self._log: deque[dict] = deque(maxlen=_LOG_LIMIT)
        self._log_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        """Слушатель поднят. Модели пайплайна к этому не привязаны."""
        return bool(self._listening and self._httpd is not None)

    def set_runner(self, runner: Callable[[RemoteJob], None] | None) -> None:
        """Подключить реальный пайплайн, когда воркер готов.

        Задания, пришедшие раньше, стартуют здесь. В конце пайплайна
        воркер вызывает ``job.finish(png)`` или ``server.complete(job_id, png)``.
        """
        self.queue.set_runner(runner)

    def complete(self, job_id: str, png: bytes) -> None:
        """Завершить задание готовым PNG. Тот же эффект, что у ``RemoteJob.finish``."""
        self.queue.complete(job_id, png)

    def start(self, host: str, port: int) -> int:
        """Слушать ``host:port``. Порт ``0`` — свободный. Вернуть фактический порт."""
        if self._httpd is not None:
            raise RuntimeError("Сервер уже запущен")
        bind_host = str(host or "0.0.0.0")
        if isinstance(port, bool):
            raise OSError(f"Некорректный порт: {port}")
        number = int(port)
        if number < 0 or number > 65535:
            raise OSError(f"Некорректный порт: {port}")
        httpd = _RemoteHTTP((bind_host, number), _make_handler(), self)
        self._httpd = httpd
        self.host = bind_host
        self.port = int(httpd.server_address[1])
        self._listening = True
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="ilt-remote",
            daemon=True,
        )
        self._thread.start()
        try:
            self._probe()
        except OSError:
            self.shutdown()
            raise
        return self.port

    def wait(self) -> None:
        """Ждать, пока другой поток не вызовет ``shutdown``."""
        thread = self._thread
        if thread is None:
            return
        while thread.is_alive():
            thread.join(timeout=0.5)

    def shutdown(self) -> None:
        """Остановить слушатель. Повторный вызов ничего не делает."""
        self._listening = False
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                logger.exception("Удалённый API не остановился")
            try:
                httpd.server_close()
            except Exception:
                logger.exception("Сокет удалённого API не закрылся")
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2)

    def recent_requests(self) -> list[dict]:
        """Последние 50 ответов: time, path, status, token_id. Без тел и сырых токенов."""
        with self._log_lock:
            return [dict(item) for item in self._log]

    def status_snapshot(self) -> dict:
        """Сводка для локального UI. Код не перевыпускает, ``token_hash`` не отдаёт."""
        devices = _public_devices(self.settings.remote_devices)
        code = self.pairing.current_code()
        return {
            "enabled": self.ready,
            "port": self.port,
            "addresses": _lan_ipv4(),
            "pairing_code": code or "",
            "devices": devices,
            "recent": self.recent_requests(),
            "clients": len(devices),
        }

    def note(self, path: str, status: int, token_id: str) -> None:
        record = {
            "time": float(self._clock()),
            "path": str(path).split("?", 1)[0][:200],
            "status": int(status),
            "token_id": str(token_id or ""),
        }
        with self._log_lock:
            self._log.append(record)

    def begin_request(self, token: str, *, meter: bool = True) -> Device:
        """Устройство по Bearer-токену. 401, если токен чужой.

        ``meter=False`` не тратит лимит частоты. Опрос ``GET /v1/jobs/{id}``
        идёт чаще, чем лимит, и не должен становиться 429, пока страница переводится.
        """
        with self._auth_lock:
            device = self._device_for(token)
            if device is None:
                raise _HttpError(401, "Нужна авторизация")
            if meter and not self.limiter.allow(device.id):
                raise _HttpError(429, "Слишком много запросов")
            return device

    def accept_code(self, code: str, name: str = "") -> tuple[str, str] | None:
        """Обменять код на сырой токен и id. None — код неверный, просрочен или использован."""
        label = str(name or "").strip()[:200]
        with self._auth_lock:
            token = self.pairing.redeem(code)
            if token is None:
                return None
            device = make_device(token, name=label, clock=self._clock)
            devices = list(self.settings.remote_devices)
            devices.append(device.to_dict())
            self.settings.remote_devices = devices
            device_id = device.id
            token_hash = device.token_hash
        remember_hash(device_id, token_hash)
        self._persist()
        return token, device_id

    def revoke(self, device_id: str) -> None:
        """Убрать хеш устройства. Старый токен перестаёт проходить."""
        with self._auth_lock:
            kept = drop_device(self.settings.remote_devices, device_id)
            self.settings.remote_devices = [item.to_dict() for item in kept]
        self._persist()

    def submit_image(
        self,
        device: Device,
        image: bytes,
        source_lang: str,
        target_lang: str,
        *,
        fresh: bool = False,
    ) -> RemoteJob:
        """Поставить перевод. При кэше задание уже ``done`` и раннер не вызывается.

        ``fresh`` пропускает чтение кэша. Готовый результат всё равно записывается.
        """
        source = source_lang.strip().lower()
        target = target_lang.strip().lower()
        if not source or not target:
            raise _HttpError(400, "Нужны языки")
        if not image:
            raise _HttpError(400, "Пустой файл")
        width, height = _image_size(image)
        if pixel_too_large(width, height):
            raise _HttpError(413, "Слишком большое изображение")
        key = CacheKey.build(image, source, target, _pipeline_fingerprint(self.settings))
        cached = None if fresh else self._cache_get(key)
        job = RemoteJob(
            image=image,
            source_lang=source,
            target_lang=target,
            device_id=device.id,
            cache_key=key,
        )
        if cached is not None:
            job.result = cached
            job.status = "done"
            job.stage = "cache"
            job.progress = 100
            job.error = ""
        self._attach_inbox(job)
        if cached is not None:
            self.queue.remember(job)
            return job
        try:
            self.queue.submit(job)
        except QueueFull:
            job.status = "error"
            job.stage = "error"
            job.error = "Очередь заполнена"
            self._sync_page(job)
            raise _HttpError(429, "Очередь заполнена") from None
        return job

    def _device_for(self, token: str) -> Device | None:
        if not token:
            return None
        try:
            return find_device(self.settings.remote_devices, token)
        except (KeyError, TypeError, ValueError):
            return None

    def _persist(self) -> None:
        path = self._settings_path
        if path is None:
            return
        try:
            self.settings.save(path)
        except OSError:
            logger.exception("Настройки устройств не сохранились")

    def _cache_get(self, key: CacheKey) -> bytes | None:
        with self._io:
            return self.cache.get(key)

    def _cache_result(self, job: RemoteJob) -> None:
        if not job.result:
            return
        with self._io:
            self.cache.put(job.cache_key, job.result)

    def _probe(self) -> None:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        deadline = time.time() + 2
        last: Exception | None = None
        while time.time() < deadline:
            try:
                conn = HTTPConnection(host, self.port, timeout=0.3)
                try:
                    conn.request("GET", "/v1/health")
                    response = conn.getresponse()
                    response.read()
                    if response.status == 200:
                        return
                finally:
                    conn.close()
            except OSError as exc:
                last = exc
            time.sleep(0.02)
        raise OSError(f"Удалённый API не ответил на {host}:{self.port}") from last

    def _attach_inbox(self, job: RemoteJob) -> None:
        path = self._write_inbox_file(job)
        store = self.store
        if store is None or path is None:
            return
        try:
            with self._io:
                project = self._inbox_project(store, job.source_lang, job.target_lang)
                added = store.add_sources(str(project["id"]), [path])
                if not added:
                    return
                job.project_id = str(project["id"])
                job.page_id = str(added[0]["id"])
                self._write_page(store, job)
        except Exception:
            logger.exception("Проект «Входящие» не обновлён")

    def _inbox_project(self, store, source_lang: str, target_lang: str) -> dict:
        for project in store.list_projects():
            if str(project.get("name") or "") == INBOX_NAME:
                return project
        return store.create_project(INBOX_NAME, source_lang, target_lang)

    def _sync_page(self, job: RemoteJob) -> None:
        store = self.store
        if store is None or not job.project_id or not job.page_id:
            return
        try:
            with self._io:
                self._write_page(store, job)
        except Exception:
            logger.exception("Страница «Входящие» не обновлена")

    def _write_page(self, store, job: RemoteJob) -> None:
        status = job.status if job.status in ("queued", "running", "done", "error") else "error"
        store.update_status(
            job.project_id,
            job.page_id,
            status=status,
            stage=job.stage,
            error=job.error,
        )
        if status == "done" and job.result:
            with Image.open(BytesIO(job.result)) as image:
                image.load()
                store.save_image(job.project_id, job.page_id, "result", image)

    def _write_inbox_file(self, job: RemoteJob) -> Path | None:
        try:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            path = self.inbox_dir / f"{job.id}.png"
            with Image.open(BytesIO(job.image)) as image:
                image.load()
                image.save(path, "PNG")
        except Exception:
            logger.warning("Исходник для «Входящие» не записан", exc_info=True)
            return None
        return path


def _bearer(header: str | None) -> str:
    if not header:
        return ""
    scheme, _, rest = header.strip().partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return ""
    return rest.strip()


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            try:
                self.request.settimeout(15)
            except Exception:
                return

        def log_message(self, fmt: str, *args) -> None:
            logger.debug("%s %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._dispatch()

        def _remote(self) -> RemoteServer:
            return self.server.remote  # type: ignore[attr-defined]

        def _dispatch(self) -> None:
            self.close_connection = True
            self._sent = False
            self._token_id = ""
            self._origin = _cors_origin(self.headers.get("Origin"))
            self._route_path = unquote(urlparse(self.path).path)
            status = 500
            try:
                status = self._route()
            except _HttpError as exc:
                status = exc.status
                self._send_json(exc.payload, exc.status)
            except Exception:
                logger.exception("Сбой удалённого API %s", self._route_path)
                status = 500
                self._send_json({"error": "Внутренняя ошибка"}, 500)
            finally:
                try:
                    self._remote().note(self._route_path, status, self._token_id)
                except Exception:
                    logger.debug("Запрос не записан в журнал", exc_info=True)

        def _route(self) -> int:
            path = self._route_path
            if self.command == "OPTIONS":
                if not self._origin:
                    self._send_empty(403)
                    return 403
                self._send_empty(204)
                return 204
            remote = self._remote()
            if self.command == "GET" and path == "/v1/health":
                self._send_json({"version": API_VERSION, "ready": remote.ready}, 200)
                return 200
            if self.command == "POST" and path == "/v1/pair":
                return self._pair(remote)
            status_poll = self.command == "GET" and _JOB.fullmatch(path) is not None
            device = remote.begin_request(
                _bearer(self.headers.get("Authorization")),
                meter=not status_poll,
            )
            self._token_id = device.id
            if self.command == "POST" and path == "/v1/translate":
                return self._translate(remote, device)
            result = _JOB_RESULT.fullmatch(path)
            if result is not None and self.command == "GET":
                return self._result(remote, device, result.group(1))
            found = _JOB.fullmatch(path)
            if found is not None and self.command == "GET":
                return self._job(remote, device, found.group(1))
            if found is not None and self.command == "DELETE":
                return self._delete(remote, device, found.group(1))
            raise _HttpError(404, "Не найдено")

        def _pair(self, remote: RemoteServer) -> int:
            body = self._read_body()
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise _HttpError(400, "Ожидался JSON") from None
            if not isinstance(data, dict):
                raise _HttpError(400, "Ожидался объект")
            code = _pair_code(data.get("code"))
            name = data.get("name") if isinstance(data.get("name"), str) else ""
            accepted = remote.accept_code(code, name)
            if accepted is None:
                raise _HttpError(401, "Неверный код")
            token, device_id = accepted
            self._token_id = device_id
            self._send_json({"token": token}, 200)
            return 200

        def _translate(self, remote: RemoteServer, device: Device) -> int:
            image, source_lang, target_lang, fresh = self._upload()
            job = remote.submit_image(
                device, image, source_lang, target_lang, fresh=fresh
            )
            self._send_json({"job_id": job.id}, 202)
            return 202

        def _job(self, remote: RemoteServer, device: Device, job_id: str) -> int:
            view = remote.queue.view(job_id, device.id)
            if view is None:
                raise _HttpError(404, "Задание не найдено")
            self._send_json(view, 200)
            return 200

        def _result(self, remote: RemoteServer, device: Device, job_id: str) -> int:
            kind, png = remote.queue.result_bytes(job_id, device.id)
            if kind == "missing":
                raise _HttpError(404, "Задание не найдено")
            if kind != "ready" or not png:
                raise _HttpError(409, "Результат ещё не готов")
            self._send_bytes(200, "image/png", png)
            return 200

        def _delete(self, remote: RemoteServer, device: Device, job_id: str) -> int:
            if not remote.queue.delete(job_id, device.id):
                raise _HttpError(404, "Задание не найдено")
            self._send_empty(204)
            return 204

        def _upload(self) -> tuple[bytes, str, str, bool]:
            body = self._read_body()
            content_type = self.headers.get("Content-Type") or ""
            if content_type.lower().startswith("multipart/form-data"):
                fields = parse_multipart(body, content_type)
                image = fields.get("file") or b""
                source = _field_text(fields.get("source_lang")) or (
                    self.headers.get("X-Source-Lang") or ""
                )
                target = _field_text(fields.get("target_lang")) or (
                    self.headers.get("X-Target-Lang") or ""
                )
                fresh = _fresh_flag(_field_text(fields.get("fresh")))
                return image, source, target, fresh
            return (
                body,
                self.headers.get("X-Source-Lang") or "",
                self.headers.get("X-Target-Lang") or "",
                False,
            )

        def _read_body(self) -> bytes:
            raw = self.headers.get("Content-Length")
            if raw is None:
                data = self.rfile.read(MAX_BODY_BYTES + 1)
                if body_too_large(len(data)):
                    raise _HttpError(413, "Тело больше 20 МиБ")
                return data
            try:
                size = int(str(raw).strip())
            except (TypeError, ValueError):
                raise _HttpError(400, "Некорректный Content-Length") from None
            if size < 0:
                raise _HttpError(400, "Некорректный Content-Length")
            if body_too_large(size):
                raise _HttpError(413, "Тело больше 20 МиБ")
            return self.rfile.read(size)

        def _apply_cors(self) -> None:
            origin = self._origin
            if not origin:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", _ALLOW_METHODS)
            self.send_header("Access-Control-Allow-Headers", _ALLOW_HEADERS)
            self.send_header("Vary", "Origin")

        def _send_json(self, payload: dict, status: int) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", body)

        def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            if self._sent:
                return
            self._sent = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self._apply_cors()
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _send_empty(self, status: int) -> None:
            if self._sent:
                return
            self._sent = True
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self._apply_cors()
            self.end_headers()

    return Handler


def _public_devices(devices) -> list[dict]:
    """Устройства для UI: id, имя, время. Хеш токена не копируется."""
    public: list[dict] = []
    for item in devices or []:
        raw = item.to_dict() if hasattr(item, "to_dict") else item
        if not isinstance(raw, dict):
            continue
        public.append({
            "id": str(raw.get("id") or ""),
            "name": str(raw.get("name") or ""),
            "created": raw.get("created", 0),
        })
    return public


def _remember_ipv4(found: list[str], ip: str) -> None:
    text = str(ip or "").split("%", 1)[0].strip()
    if not text or text in found:
        return
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return
    if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast:
        return
    found.append(text)


def _lan_ipv4() -> list[str]:
    """IPv4 LAN. Петля пропускается; ``127.0.0.1`` только если других адресов нет."""
    found: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        try:
            _remember_ipv4(found, info[4][0])
        except (IndexError, TypeError):
            continue
    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Пакет не уходит: так стек называет адрес выбранного интерфейса.
        probe.connect(("192.0.2.1", 9))
        _remember_ipv4(found, probe.getsockname()[0])
    except OSError:
        pass
    finally:
        if probe is not None:
            probe.close()
    if found:
        return found
    return ["127.0.0.1"]


def _pair_code(value) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        if 0 <= value <= 999_999:
            return f"{value:06d}"
        return str(value)
    return str(value).strip()
