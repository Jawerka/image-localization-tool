"""Проверяемая докачка артефактов: постоянный кэш, пауза и OS-блокировки."""

from __future__ import annotations

import errno
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.config import Config

CHUNK = 256 * 1024
_held = threading.local()


class DownloadError(RuntimeError):
    """Загрузка временно недоступна, подтверждённый прогресс сохранён."""


class IntegrityError(DownloadError):
    """Содержимое не соответствует фиксированному каталогу."""


class DiskError(DownloadError):
    """Недостаточно свободного места."""


class BusyError(DownloadError):
    """Другой процесс уже изменяет компоненты."""


class Paused(DownloadError):
    """Пользователь приостановил подготовку."""


@dataclass(frozen=True)
class Artifact:
    """Неизменяемый файл с проверенными источниками одинакового содержимого."""

    name: str
    urls: tuple[str, ...]
    sha256: str
    size_bytes: int

    def __post_init__(self):
        if (not self.name or self.name in (".", "..") or any(c in self.name for c in "/\\:")
                or not re.fullmatch(r"[0-9a-f]{64}", self.sha256) or self.size_bytes <= 0
                or not self.urls or any(not url.startswith(("https://", "http://", "file://")) for url in self.urls)):
            raise ValueError("Некорректная запись артефакта")


def cache_root() -> Path:
    """Кэш размещается вместе с доступными для записи компонентами."""
    from src.utils.paths import components_root

    return components_root() / ".downloads"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            value.update(chunk)
    return value.hexdigest()


def valid(path: Path, item: Artifact) -> bool:
    return path.is_file() and path.stat().st_size == item.size_bytes and digest(path) == item.sha256


def atomic_json(path: Path, payload: dict) -> None:
    """Уникальный временный файл не конфликтует с записью из другого потока."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_space(path: Path, required: int, reserve: int | None = None) -> None:
    """Проверить свободное место на фактическом диске назначения."""
    path.mkdir(parents=True, exist_ok=True)
    margin = Config().download_disk_reserve_mb * 1024 * 1024 if reserve is None else reserve
    if shutil.disk_usage(path).free < max(0, required) + margin:
        raise DiskError(f"Недостаточно места: нужно ещё {(required + margin + 999999) // 1000000} МБ")


@contextmanager
def file_lock(path: Path):
    """OS-lock снимается при падении процесса; повторный вход одного потока допустим."""
    key = str(path.resolve())
    held = getattr(_held, "paths", {})
    if key in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BusyError("Другой процесс уже устанавливает компоненты. Дождитесь завершения.") from exc
        held[key] = True
        _held.paths = held
        try:
            yield
        finally:
            held.pop(key, None)
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def installer_lock():
    from src.utils.paths import components_root

    return file_lock(components_root() / ".installer.lock")


def check_pause(pause) -> None:
    if pause is not None and pause.is_set():
        raise Paused("Загрузка приостановлена. Её можно продолжить.")


def wait_retry(attempt: int, retry_after: str | None, pause=None) -> None:
    delay = min(30.0, 2 ** attempt + random.random())
    if retry_after and retry_after.isdigit():
        delay = min(30.0, float(retry_after))
    if pause is not None:
        pause.wait(delay)
        check_pause(pause)
    else:
        time.sleep(delay)


def fetch(item: Artifact, cache: Path | None = None, progress=None, pause=None,
          retries: int | None = None, timeout: float | None = None) -> Path:
    """Скачать/продолжить файл; вернуть только после полной проверки SHA256."""
    cache = Path(cache) if cache is not None else cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    ready = cache / f"{item.sha256}.blob"
    partial = cache / f"{item.sha256}.part"
    metadata = cache / f"{item.sha256}.json"
    retries = Config().download_retries if retries is None else retries
    timeout = Config().download_timeout if timeout is None else timeout
    with file_lock(cache / f"{item.sha256}.lock"):
        check_pause(pause)
        previous_root = os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT", "")
        if previous_root and not ready.exists() and not partial.exists():
            previous_cache = Path(previous_root) / ".downloads"
            if previous_cache.is_dir():
                try:
                    with file_lock(previous_cache / f"{item.sha256}.lock"):
                        old = previous_cache / ready.name
                        if valid(old, item):
                            ensure_space(cache, item.size_bytes)
                            shutil.copyfile(old, partial)
                        else:
                            old = previous_cache / partial.name
                            if old.is_file() and 0 < old.stat().st_size < item.size_bytes:
                                ensure_space(cache, old.stat().st_size)
                                shutil.copyfile(old, partial)
                        meta = previous_cache / metadata.name
                        if meta.is_file() and partial.exists():
                            shutil.copyfile(meta, metadata)
                except (BusyError, PermissionError):
                    # Прежняя папка может быть доступна только для чтения или занята.
                    # Новая установка продолжит загрузку в выбранной папке.
                    pass
        if valid(ready, item):
            if progress:
                progress(item.size_bytes, item.size_bytes)
            return ready
        ready.unlink(missing_ok=True)
        if partial.exists() and partial.stat().st_size >= item.size_bytes:
            if valid(partial, item):
                partial.replace(ready)
                return ready
            partial.unlink(missing_ok=True)
        offset = partial.stat().st_size if partial.exists() else 0
        ensure_space(cache, item.size_bytes - offset)
        last_error = None
        for url in item.urls:
            for attempt in range(retries + 1):
                check_pause(pause)
                try:
                    _receive(item, url, partial, metadata, progress, pause, timeout)
                    if not valid(partial, item):
                        partial.unlink(missing_ok=True)
                        raise IntegrityError(f"Не сходится размер или sha256 файла {item.name}")
                    partial.replace(ready)
                    if progress:
                        progress(item.size_bytes, item.size_bytes)
                    return ready
                except Paused:
                    raise
                except IntegrityError as exc:
                    last_error = exc
                    partial.unlink(missing_ok=True)
                    break
                except urllib.error.HTTPError as exc:
                    last_error = DownloadError(f"Источник временно недоступен (HTTP {exc.code}). Прогресс сохранён.")
                    if exc.code == 416:
                        partial.unlink(missing_ok=True)
                        if attempt < retries:
                            continue
                    if exc.code not in (408, 429, 500, 502, 503, 504) or attempt >= retries:
                        break
                    wait_retry(attempt, exc.headers.get("Retry-After"), pause)
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                        http.client.IncompleteRead) as exc:
                    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
                        raise DiskError("Недостаточно места. Прогресс сохранён.") from exc
                    if isinstance(exc, PermissionError):
                        raise PermissionError("Нет доступа к папке компонентов. Выберите доступную папку.") from exc
                    last_error = DownloadError("Соединение прервано. Прогресс сохранён; попробуйте продолжить.")
                    if attempt < retries:
                        wait_retry(attempt, None, pause)
            if isinstance(last_error, IntegrityError):
                continue
        raise last_error or DownloadError("Не удалось скачать компонент. Прогресс сохранён.")


def _receive(item, url, partial, metadata, progress, pause, timeout):
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "ImageLocalizationTool", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("url") == url and saved.get("etag"):
                headers["If-Range"] = saved["etag"]
        except (OSError, ValueError):
            pass
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        status = getattr(response, "status", None) or 200
        if status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if (not match or int(match[1]) != offset or int(match[3]) != item.size_bytes
                    or int(match[2]) != item.size_bytes - 1):
                raise IntegrityError("Источник вернул неверный диапазон загрузки")
        elif status == 200:
            offset = 0
        else:
            raise DownloadError(f"Неожиданный ответ источника: {status}")
        atomic_json(metadata, {"url": url, "etag": response.headers.get("ETag", "")})
        done = offset
        if progress:
            progress(done, item.size_bytes)
        with partial.open("ab" if offset else "wb") as handle:
            while True:
                check_pause(pause)
                try:
                    chunk = response.read(CHUNK)
                except http.client.IncompleteRead as exc:
                    handle.write(exc.partial)
                    raise
                if not chunk:
                    break
                if done + len(chunk) > item.size_bytes:
                    raise IntegrityError("Источник передал больше данных, чем указано в каталоге")
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, item.size_bytes)
            if done != item.size_bytes:
                raise ConnectionError("Источник оборвал передачу")


def clear_cache(cache: Path | None = None, max_bytes: int = 0) -> int:
    """Удалить старые завершённые файлы; активные/частичные загрузки сохраняются."""
    cache = Path(cache) if cache is not None else cache_root()
    removed = 0
    with installer_lock():
        files = sorted(cache.glob("*.blob"), key=lambda p: p.stat().st_mtime)
        size = sum(p.stat().st_size for p in files)
        for path in files:
            if size <= max_bytes:
                break
            try:
                with file_lock(cache / f"{path.stem}.lock"):
                    count = path.stat().st_size
                    path.unlink()
                    size -= count
                    removed += count
            except BusyError:
                continue
    return removed
