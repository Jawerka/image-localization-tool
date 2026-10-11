"""Компоненты рантайма: манифест, установка, удаление и активация паков.

Пак — набор официальных pip-колёс (schema 2, ``format:"wheels"``) либо архив
``.7z`` со старым ``site-packages`` (schema 1, совместимость). Установка:
скачать файлы в ``.parts``/``.part``, сверить sha256 каждого, распаковать в
``<runtime>/<id>.tmp``, записать маркер ``pack.json`` и атомарно переименовать
в ``<runtime>/<id>``. Колёса распаковываются пофайлово (без ``extractall``) с
проверкой путей и правилом конфликтов. Активация добавляет ``site-packages``
в ``sys.path`` и ``torch/lib`` — в DLL-поиск Windows; вызывается при старте
sidecar и в spawn-ребёнке воркера до первого импорта torch.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from src.app import __version__
from src.app.events import WorkerEvent
from src.utils.logger import logger
from src.utils.paths import install_root

PACKS_DIR_NAME = "runtime"
MARKER_NAME = "pack.json"
MANIFEST_BASENAME = "runtime_manifest.json"
PART_SUFFIX = ".part"
WHEELS_PART_SUFFIX = ".parts"
TMP_SUFFIX = ".tmp"
STDLIB_ZIP_NAME = "stdlib.zip"
RELEASE_BASE = "https://github.com/Jawerka/image-localization-tool/releases/download"
MANIFEST_ENV = "ILT_RUNTIME_MANIFEST_URL"

_CHUNK = 256 * 1024
_DOWNLOAD_TIMEOUT = 30
_MANIFEST_TIMEOUT = 8

# Порядок активации: torch-пак с CUDA вставляется в sys.path последним и
# выигрывает у CPU-пака, если установлены оба (нештатная ситуация).
_ACTIVATION_ORDER = {"torch-cpu": 0, "torch-cu128": 1, "argos": 2}

_manifest_cache: dict = {"data": None, "fetched": False, "started": False}
_ready_cache: dict = {"checked": False, "torch": False, "cuda": False}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class WheelFile:
    """Файл колеса в записи schema 2 (``format:"wheels"``)."""

    name: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Pack:
    """Запись манифеста, отфильтрованная под текущую платформу."""

    id: str
    title: str
    kind: str
    platform: str
    python: str
    version: str
    url: str
    sha256: str
    size_bytes: int
    driver_min: int | None = None
    format: str = ""
    files: tuple[WheelFile, ...] = ()
    source: str = ""

    @property
    def site_packages_name(self) -> str:
        return "site-packages"

    @property
    def is_wheels(self) -> bool:
        return bool(self.files)

    @property
    def effective_size(self) -> int:
        """Размер записи: суммарный по файлам или объявленный (archive)."""
        if self.files:
            return sum(item.size_bytes for item in self.files)
        return self.size_bytes


def _is_sha256(text: str) -> bool:
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _source_from_url(url: str) -> str:
    """Человекочитаемый источник файла по хосту URL."""
    try:
        host = urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""
    host = host.casefold()
    if host.endswith("pythonhosted.org"):
        return "PyPI"
    if host.endswith("pytorch.org"):
        return "PyTorch CDN"
    if host.endswith("github.com") or host.endswith("githubusercontent.com"):
        return "GitHub releases"
    return host


def _source_label(urls: list[str]) -> str:
    labels: list[str] = []
    for url in urls:
        label = _source_from_url(url)
        if label and label not in labels:
            labels.append(label)
    return " + ".join(labels)


def platform_tag() -> str:
    """Тег платформы пака: ``win`` или ``linux``."""
    return "win" if sys.platform == "win32" else "linux"


def python_tag() -> str:
    """Тег интерпретатора пака: ``310``/``311``/…"""
    return f"{sys.version_info.major}{sys.version_info.minor}"


def runtime_root() -> Path:
    """Каталог установленных паков: ``<install_root>/runtime``."""
    return install_root() / PACKS_DIR_NAME


def pack_dir(pack_id: str) -> Path:
    return runtime_root() / _safe_id(pack_id)


def manifest_url() -> str:
    """URL манифеста: переменная среды или ассет релиза текущей версии."""
    override = os.environ.get(MANIFEST_ENV, "").strip()
    if override:
        return override
    return f"{RELEASE_BASE}/v{__version__}/ilt-runtime-manifest-{__version__}.json"


def bundled_manifest_path() -> Path | None:
    """Встроенная копия манифеста: ``_internal/src/app`` в сборке, иначе репозиторий."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "src" / "app" / MANIFEST_BASENAME
        if candidate.is_file():
            return candidate
    source = Path(__file__).with_name(MANIFEST_BASENAME)
    if source.is_file():
        return source
    return None


def _read_manifest_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        logger.warning("Манифест рантайма не читается: %s", path)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        logger.warning("Манифест рантайма неверного формата: %s", path)
        return None
    return data


def _fetch_manifest(url: str) -> dict | None:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"ImageLocalizationTool/{__version__}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_MANIFEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.info("Манифест рантайма недоступен (%s): %s", url, exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("packs"), list):
        return None
    return payload


def load_manifest(force: bool = False) -> dict:
    """Манифест: кэш → встроенная копия сразу, свежая версия — фоном.

    Если задан ``ILT_RUNTIME_MANIFEST_URL`` (тесты, отладка), он загружается
    синхронно и считается источником истины. Иначе ответ не блокируется сетью:
    возвращается встроенный манифест, а фоновый поток обновляет кэш для
    следующих вызовов.
    """
    with _cache_lock:
        cached = _manifest_cache["data"]
        if force:
            cached = None
    if cached is not None:
        return cached

    override = os.environ.get(MANIFEST_ENV, "").strip()
    if override:
        fetched = _fetch_manifest(override)
        if fetched is not None:
            with _cache_lock:
                _manifest_cache["data"] = fetched
            return fetched

    bundled_path = bundled_manifest_path()
    bundled = _read_manifest_file(bundled_path) if bundled_path else None
    if bundled is None:
        bundled = {"schema": 1, "app": __version__, "packs": []}

    # Платформа без встроенных записей (Linux-база до релизного манифеста):
    # тянем манифест синхронно, иначе --deploy на сервере не увидит паков.
    if not _has_platform_packs(bundled):
        fetched = _fetch_manifest(manifest_url())
        if fetched is not None:
            with _cache_lock:
                _manifest_cache["data"] = fetched
            return fetched

    with _cache_lock:
        _manifest_cache["data"] = bundled
        if not override and not _manifest_cache["started"]:
            _manifest_cache["started"] = True
            _start_background_refresh()

    return bundled


def _record_has_hash(raw: dict) -> bool:
    """Есть ли у записи настоящие хэши: sha256 (archive) или files[] (wheels)."""
    if str(raw.get("sha256") or "").strip():
        return True
    files = raw.get("files")
    if isinstance(files, list) and files:
        return all(
            isinstance(item, dict)
            and _is_sha256(str(item.get("sha256") or "").strip().casefold())
            for item in files
        )
    return False


def _has_platform_packs(manifest: dict) -> bool:
    """Есть ли пак текущей платформы с настоящими хэшами.

    Плейсхолдеры без sha (встроенные записи Linux до релизного манифеста)
    не считаются: база должна синхронно получить релизный манифест.
    """
    current_os = platform_tag()
    current_py = python_tag()
    for raw in manifest.get("packs") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("os") or raw.get("platform") or "") != current_os:
            continue
        if str(raw.get("python") or current_py) != current_py:
            continue
        if _record_has_hash(raw):
            return True
    return False


def _start_background_refresh() -> None:
    def refresh() -> None:
        fetched = _fetch_manifest(manifest_url())
        if fetched is None:
            return
        with _cache_lock:
            _manifest_cache["data"] = fetched
        logger.info("Манифест рантайма обновлён из релиза")

    threading.Thread(target=refresh, name="ilt-manifest", daemon=True).start()


def platform_packs(manifest: dict | None = None) -> list[Pack]:
    """Паки текущей платформы и версии Python, в порядке манифеста."""
    data = manifest if manifest is not None else load_manifest()
    current_os = platform_tag()
    current_py = python_tag()
    result: list[Pack] = []
    for raw in data.get("packs") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("os") or raw.get("platform") or "") != current_os:
            continue
        if str(raw.get("python") or current_py) != current_py:
            continue
        pack = _pack_from_dict(raw)
        if pack is not None and pack.id not in {item.id for item in result}:
            result.append(pack)
    return result


def _files_from_raw(raw: dict) -> tuple[WheelFile, ...]:
    """Разобрать ``files[]`` записи schema 2.

    ``ValueError`` — запись невалидна и должна быть пропущена целиком.
    """
    raw_files = raw.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("files пуст")
    files: list[WheelFile] = []
    names: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError("элемент files — не объект")
        name = PurePosixPath(str(item.get("name") or "").replace("\\", "/")).name
        url = str(item.get("url") or "").strip()
        sha = str(item.get("sha256") or "").strip().casefold()
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if not name or name in names or not url or not _is_sha256(sha) or size <= 0:
            raise ValueError(f"некорректный файл: {name or '?'}")
        names.add(name)
        files.append(WheelFile(name=name, url=url, sha256=sha, size_bytes=size))
    return tuple(files)


def _pack_from_dict(raw: dict) -> Pack | None:
    pack_id = str(raw.get("id") or "").strip()
    if not pack_id:
        return None
    driver_min = raw.get("driver_min")
    gpu = raw.get("gpu")
    if driver_min is None and isinstance(gpu, dict):
        driver_min = gpu.get("driver_min")
    try:
        driver_value = int(driver_min) if driver_min is not None else None
    except (TypeError, ValueError):
        driver_value = None
    try:
        size_value = int(raw.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size_value = 0
    url_value = str(raw.get("url") or "")
    format_value = str(raw.get("format") or "").strip().casefold()
    files: tuple[WheelFile, ...] = ()
    if "files" in raw or format_value == "wheels":
        try:
            files = _files_from_raw(raw)
        except ValueError as exc:
            logger.warning("Запись %s манифеста пропущена: %s", pack_id, exc)
            return None
        computed = sum(item.size_bytes for item in files)
        if size_value not in (0, computed):
            logger.warning(
                "Запись %s манифеста пропущена: size_bytes %s ≠ сумма файлов %s",
                pack_id,
                size_value,
                computed,
            )
            return None
        size_value = computed
    if files:
        source = _source_label([item.url for item in files])
        pack_format = "wheels"
    else:
        source = _source_from_url(url_value)
        pack_format = format_value or "archive"
    return Pack(
        id=pack_id,
        title=str(raw.get("title") or pack_id),
        kind=str(raw.get("kind") or "other"),
        platform=str(raw.get("os") or raw.get("platform") or ""),
        python=str(raw.get("python") or ""),
        version=str(raw.get("version") or ""),
        url=url_value,
        sha256=str(raw.get("sha256") or "").strip().lower(),
        size_bytes=size_value,
        driver_min=driver_value,
        format=pack_format,
        files=files,
        source=source,
    )


def pack_by_id(pack_id: str, manifest: dict | None = None) -> Pack:
    """Пак текущей платформы по id. ``KeyError`` — такого пака нет."""
    wanted = _safe_id(pack_id)
    for pack in platform_packs(manifest):
        if pack.id == wanted:
            return pack
    raise KeyError(pack_id)


def _safe_id(pack_id: str) -> str:
    text = str(pack_id or "").strip()
    if not text or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in text):
        raise ValueError("Некорректный id компонента")
    return text


def installed_ids() -> list[str]:
    """ids паков с валидным маркером и каталогом ``site-packages``."""
    root = runtime_root()
    if not root.is_dir():
        return []
    found: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or entry.name.endswith(TMP_SUFFIX):
            continue
        if _installed_dir_ok(entry):
            found.append(entry.name)
    return found


def _installed_dir_ok(directory: Path) -> bool:
    marker = directory / MARKER_NAME
    if not marker.is_file() or not (directory / "site-packages").is_dir():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and bool(data.get("id"))


def installed_version(pack_id: str) -> str:
    """Версия установленного пака или пустая строка."""
    directory = pack_dir(pack_id)
    marker = directory / MARKER_NAME
    if not _installed_dir_ok(directory):
        return ""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    return str(data.get("version") or "")


def is_installed(pack_id: str) -> bool:
    try:
        directory = pack_dir(pack_id)
    except ValueError:
        return False
    return _installed_dir_ok(directory)


def directory_bytes(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def status(device: str = "auto") -> dict:
    """Снимок для API: паки, железо, доступность torch/Argos, устройство."""
    from src.app import hardware

    manifest = load_manifest()
    hw = hardware.detect()
    recommended = str(hw.get("recommended") or "torch-cpu")
    entries: list[dict] = []
    for pack in platform_packs(manifest):
        installed = is_installed(pack.id)
        entries.append(
            {
                "id": pack.id,
                "title": pack.title,
                "kind": pack.kind,
                "version": pack.version,
                "size_bytes": pack.effective_size,
                "format": pack.format,
                "source": pack.source,
                "state": "installed" if installed else "available",
                "installed_version": installed_version(pack.id) if installed else "",
                "installed_bytes": directory_bytes(pack_dir(pack.id)) if installed else 0,
                "recommended": pack.id == recommended,
                "driver_min": pack.driver_min,
                "error": "",
            }
        )
    torch_ok, cuda_ok = torch_state()
    return {
        "platform": platform_tag(),
        "python": python_tag(),
        "packs": entries,
        "hardware": hw,
        "torch_ready": torch_ok,
        "argos_ready": argos_ready(),
        "device": str(device or "auto"),
        "device_effective": effective_device(device, torch_ok, cuda_ok),
        "download": {"id": "", "state": "idle"},
    }


def summary(device: str = "auto") -> dict:
    """Короткая сводка для ``/api/bootstrap``."""
    from src.app import hardware

    torch_ok, cuda_ok = torch_state()
    return {
        "installed": installed_ids(),
        "recommended": str(hardware.detect().get("recommended") or "torch-cpu"),
        "torch_ready": torch_ok,
        "argos_ready": argos_ready(),
        "device_effective": effective_device(device, torch_ok, cuda_ok),
    }


def effective_device(device: str, torch_ok: bool | None = None, cuda_ok: bool | None = None) -> str:
    """Какое устройство реально получит ``auto``."""
    preference = str(device or "auto")
    if preference and preference != "auto":
        return preference
    if torch_ok is None or cuda_ok is None:
        torch_ok, cuda_ok = torch_state()
    if torch_ok and cuda_ok:
        return "cuda"
    return "cpu"


def torch_state(refresh: bool = False) -> tuple[bool, bool]:
    """``(torch импортируется, CUDA доступна)``. Импорт torch — один раз, лениво.

    Если torch-пак не установлен и torch ещё не импортирован, импорт не
    форсируется: базе без пака незачем платить секунды за проверку.
    """
    with _cache_lock:
        if refresh:
            _ready_cache["checked"] = False
        if _ready_cache["checked"]:
            return bool(_ready_cache["torch"]), bool(_ready_cache["cuda"])

    has_pack = any(pack.kind == "torch" and is_installed(pack.id) for pack in platform_packs())
    already = sys.modules.get("torch")
    if not has_pack and already is None:
        with _cache_lock:
            _ready_cache.update({"checked": True, "torch": False, "cuda": False})
        return False, False

    torch_ok = False
    cuda_ok = False
    try:
        torch = already if already is not None else importlib.import_module("torch")
        torch_ok = True
        try:
            cuda_ok = bool(torch.cuda.is_available())
        except Exception:
            cuda_ok = False
    except Exception as exc:
        logger.info("torch недоступен: %s", exc)
    with _cache_lock:
        _ready_cache.update({"checked": True, "torch": torch_ok, "cuda": cuda_ok})
    return torch_ok, cuda_ok


def argos_ready() -> bool:
    """Argos импортируется (пак установлен или dev-venv). Без импорта самого пакета."""
    if is_installed("argos"):
        return True
    try:
        return importlib.util.find_spec("argostranslate") is not None
    except (ImportError, ValueError):
        return False


def download_and_install(pack: Pack | str, progress=None, retries: int = 1) -> Path:
    """Скачать, проверить и распаковать пак. Возвращает каталог установки.

    ``progress(done, total, state, message)`` вызывается на скачивании и
    распаковке. Wheels-записи качаются пофайлово (``.parts``), archive — одним
    архивом (``.part``). Повторная установка уже стоящего пака — no-op.
    """
    if isinstance(pack, str):
        pack = pack_by_id(pack)
    destination = pack_dir(pack.id)
    if _installed_dir_ok(destination):
        _notify(progress, 0, 0, "installed", "уже установлено")
        return destination

    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    archive = root / f"{pack.id}{PART_SUFFIX}"
    staging = root / f"{pack.id}{WHEELS_PART_SUFFIX}"
    temporary = root / f"{pack.id}{TMP_SUFFIX}"
    try:
        if pack.is_wheels:
            _download_files(pack, staging, progress, retries)
        else:
            _download_pack(pack, archive, progress, retries)
        _notify(progress, 0, 0, "installing", "распаковка")
        if pack.is_wheels:
            _extract_wheels(pack, staging, temporary)
        else:
            _extract_pack(pack, archive, temporary)
        _write_marker(temporary, pack)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    finally:
        if archive.exists():
            archive.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    activate_path(destination)
    torch_state(refresh=True)
    _notify(progress, 0, 0, "installed", "")
    return destination


def _notify(progress, done: int, total: int | None, state: str, message: str) -> None:
    if progress is None:
        return
    try:
        progress(done, total, state, message)
    except Exception:
        logger.debug("progress-колбэк упал", exc_info=True)


def _download_pack(pack: Pack, archive: Path, progress, retries: int) -> None:
    if not pack.url:
        raise RuntimeError(f"У компонента {pack.id} нет адреса загрузки")
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            _download_once(pack, archive, progress)
            return
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Сервер вернул {exc.code} для {pack.id}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            if archive.exists():
                archive.unlink(missing_ok=True)
            if attempt < retries:
                logger.info("Повтор загрузки %s (%s)", pack.id, exc)
                time.sleep(2.0 + 2.0 * attempt)
    raise RuntimeError(f"Не удалось скачать {pack.id}: {last_error}")


def _download_once(pack: Pack, archive: Path, progress) -> None:
    request = urllib.request.Request(
        pack.url, headers={"User-Agent": f"ImageLocalizationTool/{__version__}"}
    )
    hasher = hashlib.sha256()
    done = 0
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
        header = response.headers.get("Content-Length")
        try:
            total = int(header) if header else None
        except (TypeError, ValueError):
            total = None
        _notify(progress, 0, total, "downloading", "")
        with archive.open("wb") as handle:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
                done += len(chunk)
                _notify(progress, done, total, "downloading", "")
    if not pack.sha256:
        logger.warning("У компонента %s нет sha256 в манифесте — проверка пропущена", pack.id)
        return
    digest = hasher.hexdigest()
    if digest != pack.sha256:
        raise RuntimeError(f"Не сходится sha256 компонента {pack.id}")


def _download_files(pack: Pack, staging: Path, progress, retries: int) -> None:
    """Пофайлово скачать колёса записи: ``.part`` на файл, sha256 каждого."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    total = pack.effective_size
    done = 0
    for wheel in pack.files:
        target = staging / wheel.name
        part = staging / f"{wheel.name}{PART_SUFFIX}"
        last_error: Exception | None = None
        for attempt in range(max(0, retries) + 1):
            try:
                _download_file(wheel, part, progress, done, total)
                break
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"Сервер вернул {exc.code} для файла {wheel.name}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if part.exists():
                    part.unlink(missing_ok=True)
                if attempt < retries:
                    logger.info("Повтор загрузки %s (%s)", wheel.name, exc)
                    time.sleep(2.0 + 2.0 * attempt)
        else:
            raise RuntimeError(f"Не удалось скачать файл {wheel.name}: {last_error}")
        part.replace(target)
        done += wheel.size_bytes


def _download_file(wheel: WheelFile, target: Path, progress, base: int, total: int) -> None:
    request = urllib.request.Request(
        wheel.url, headers={"User-Agent": f"ImageLocalizationTool/{__version__}"}
    )
    hasher = hashlib.sha256()
    done = 0
    _notify(progress, base, total, "downloading", "")
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
        with target.open("wb") as handle:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
                done += len(chunk)
                _notify(progress, base + done, total, "downloading", "")
    digest = hasher.hexdigest()
    if wheel.sha256 and digest != wheel.sha256:
        raise RuntimeError(f"Не сходится sha256 файла {wheel.name}")


def _extract_wheels(pack: Pack, staging: Path, temporary: Path) -> None:
    """Пофайловая распаковка колёс: сортировка, zip-slip, конфликты."""
    if temporary.exists():
        shutil.rmtree(temporary)
    site = temporary / "site-packages"
    site.mkdir(parents=True)
    for wheel in sorted(pack.files, key=lambda item: item.name):
        path = staging / wheel.name
        if not path.is_file():
            raise RuntimeError(f"Нет файла колеса {wheel.name}")
        _extract_wheel(path, site)
    if not any(site.iterdir()):
        raise RuntimeError(f"Колёса пака {pack.id} пусты")


def _extract_wheel(path: Path, site: Path) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Не удалось открыть колесо {path.name}: {exc}") from exc
    with archive:
        for info in archive.infolist():
            pure = PurePosixPath(str(info.filename).replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError(f"Недопустимый путь в колесе: {info.filename}")
            parts = pure.parts
            if not parts or info.is_dir():
                continue
            if any(part.endswith(".data") for part in parts):
                continue
            target = site.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if _zip_entry_equals(archive, info, target):
                    continue
                raise RuntimeError(f"Конфликт файла между колёсами: {pure.as_posix()}")
            try:
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, _CHUNK)
            except OSError as exc:
                raise RuntimeError(f"Не удалось распаковать {info.filename}: {exc}") from exc


def _zip_entry_equals(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> bool:
    """Совпадает ли содержимое entry с уже распакованным файлом."""
    try:
        if target.stat().st_size != info.file_size:
            return False
    except OSError:
        return False
    existing = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            existing.update(chunk)
    incoming = hashlib.sha256()
    with archive.open(info) as source:
        for chunk in iter(lambda: source.read(_CHUNK), b""):
            incoming.update(chunk)
    return existing.digest() == incoming.digest()


def _extract_pack(pack: Pack, archive: Path, temporary: Path) -> None:
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover - база всегда несёт py7zr
        raise RuntimeError("Нет py7zr для распаковки компонента") from exc
    try:
        with py7zr.SevenZipFile(archive, "r") as zf:
            names = zf.getnames()
            if not names:
                raise RuntimeError(f"Пустой архив компонента {pack.id}")
            for name in names:
                pure = PurePosixPath(str(name).replace("\\", "/"))
                if pure.is_absolute() or ".." in pure.parts:
                    raise RuntimeError(f"Недопустимый путь в архиве: {name}")
            zf.extractall(path=temporary)
    except Exception as exc:
        raise RuntimeError(f"Не удалось распаковать {pack.id}: {exc}") from exc
    if not (temporary / "site-packages").is_dir():
        raise RuntimeError(f"В архиве {pack.id} нет site-packages")


def _write_marker(directory: Path, pack: Pack) -> None:
    payload = {
        "id": pack.id,
        "version": pack.version,
        "installed_at": time.time(),
    }
    if pack.is_wheels:
        payload["format"] = "wheels"
        payload["files"] = {item.name: item.sha256 for item in pack.files}
    else:
        payload["format"] = "archive"
        payload["sha256"] = pack.sha256
    (directory / MARKER_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def remove(pack_id: str, packs_root: Path | None = None) -> bool:
    """Удалить пак. False — папки не было (идемпотентно)."""
    root = Path(packs_root) if packs_root is not None else runtime_root()
    directory = root / _safe_id(pack_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    torch_state(refresh=True)
    return True


def startup() -> list[str]:
    """Старт процесса: активация паков и ``ARGOS_PACKAGES_DIR``.

    Вызывается из ``src/app/__main__.py`` и из ``worker_main`` (spawn-ребёнок
    не проходит через main) до первого импорта torch/argostranslate.
    """
    activated = activate()
    try:
        from src.app.paths import data_root

        os.environ.setdefault("ARGOS_PACKAGES_DIR", str(data_root() / "argos-packages"))
    except Exception:
        logger.debug("Не удалось задать ARGOS_PACKAGES_DIR", exc_info=True)
    return activated


def activate(packs_root: Path | None = None) -> list[str]:
    """Подключить установленные паки: ``sys.path``, DLL-каталоги, stdlib.zip."""
    _attach_stdlib()
    root = Path(packs_root) if packs_root is not None else runtime_root()
    if not root.is_dir():
        return []
    found: list[tuple[int, str, Path]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or entry.name.endswith(TMP_SUFFIX):
            continue
        if not _installed_dir_ok(entry):
            continue
        order = _ACTIVATION_ORDER.get(entry.name, 9)
        found.append((order, entry.name, entry))
    found.sort(key=lambda item: (item[0], item[1]))
    activated: list[str] = []
    for _order, pack_id, directory in found:
        if activate_path(directory):
            activated.append(pack_id)
    if activated:
        logger.info("Активированы компоненты: %s", ", ".join(activated))
    return activated


def activate_path(directory: Path) -> bool:
    """Подключить один распакованный пак (после установки — без перезапуска)."""
    site = Path(directory) / "site-packages"
    if not site.is_dir():
        return False
    text = str(site)
    if text not in sys.path:
        sys.path.insert(0, text)
    _add_dll_directories(site)
    return True


def _add_dll_directories(site: Path) -> None:
    """torch/lib (и nvidia/*/lib на Linux) — в поиск динамических библиотек."""
    if sys.platform != "win32":
        return
    candidates = [site / "torch" / "lib"]
    library_dirs = [path for path in candidates if path.is_dir()]
    if not library_dirs or not hasattr(os, "add_dll_directory"):
        return
    for library in library_dirs:
        text = str(library)
        try:
            os.add_dll_directory(text)
        except OSError:
            logger.debug("add_dll_directory не сработал: %s", text)
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    prefix = [str(item) for item in library_dirs if str(item) not in parts]
    if prefix:
        os.environ["PATH"] = os.pathsep.join(prefix + parts)


def _attach_stdlib() -> None:
    """Добавить полный stdlib базовой сборки (frozen stdlib неполон)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    stdlib = Path(meipass) / STDLIB_ZIP_NAME
    text = str(stdlib)
    if stdlib.is_file() and text not in sys.path:
        sys.path.append(text)


class Manager:
    """Фоновая установка одного пака за раз с событиями ``runtime.progress``."""

    def __init__(self, fanout=None):
        self._fanout = fanout
        self._lock = threading.Lock()
        self._state: dict = {"id": "", "state": "idle", "done": 0, "total": 0, "error": ""}
        self._thread: threading.Thread | None = None

    def current(self) -> dict:
        with self._lock:
            return dict(self._state)

    def busy(self) -> bool:
        with self._lock:
            return self._state["state"] in ("downloading", "installing")

    def start(self, pack_id: str) -> dict:
        """Запустить установку. Уже идёт другая — возвращает её состояние."""
        with self._lock:
            if self._state["state"] in ("downloading", "installing"):
                return dict(self._state)
        pack = pack_by_id(pack_id)
        if _installed_dir_ok(pack_dir(pack.id)):
            return {"id": pack.id, "state": "installed", "done": 0, "total": 0, "error": ""}
        self._update({"id": pack.id, "state": "downloading", "done": 0, "total": 0, "error": ""})
        thread = threading.Thread(target=self._run, args=(pack,), name="ilt-runtime", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return self.current()

    def _run(self, pack: Pack) -> None:
        def progress(done, total, state, message) -> None:
            payload = {
                "id": pack.id,
                "state": state,
                "done": int(done or 0),
                "total": int(total or 0),
                "error": "",
            }
            self._update(payload)

        try:
            download_and_install(pack, progress)
        except Exception as exc:
            logger.exception("Установка компонента %s не удалась", pack.id)
            self._update(
                {"id": pack.id, "state": "error", "done": 0, "total": 0, "error": str(exc)}
            )

    def _update(self, payload: dict) -> None:
        with self._lock:
            self._state = {
                "id": str(payload.get("id") or ""),
                "state": str(payload.get("state") or "idle"),
                "done": int(payload.get("done") or 0),
                "total": int(payload.get("total") or 0),
                "error": str(payload.get("error") or ""),
            }
            snapshot = dict(self._state)
        fanout = self._fanout
        if fanout is not None:
            try:
                fanout(WorkerEvent("runtime.progress", snapshot))
            except Exception:
                logger.debug("fanout runtime.progress упал", exc_info=True)
