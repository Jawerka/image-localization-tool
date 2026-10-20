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
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from src.app import __version__
from src.app.events import WorkerEvent
from src.utils.logger import logger
from src.utils.paths import components_root, install_root
from src.app import downloads

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
_ACTIVATION_ORDER = {"torch-cpu": 0, "torch-cu128": 1, "torch-cu130": 2, "argos": 3}

_manifest_cache: dict = {"data": None, "fetched": False, "started": False}
_ready_cache: dict = {"checked": False, "torch": False, "cuda": False}
_cache_lock = threading.Lock()
_dll_handles: dict[str, object] = {}


@dataclass(frozen=True)
class WheelFile:
    """Файл колеса в записи schema 2 (``format:"wheels"``)."""

    name: str
    url: str
    sha256: str
    size_bytes: int
    mirrors: tuple[str, ...] = ()


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
    check: str = ""
    unpacked_bytes: int = 0

    @property
    def revision(self) -> str:
        """Состав и ABI определяют ревизию независимо от версии приложения."""
        payload = [self.id, self.platform, self.python, self.version,
                   sorted((f.name, f.sha256, f.size_bytes) for f in self.files), self.sha256]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

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
    return components_root() / PACKS_DIR_NAME


def pack_dir(pack_id: str) -> Path:
    """Активная проверенная ревизия либо прежний каталог без миграции."""
    pack_id = _safe_id(pack_id)
    root = runtime_root()
    active = root / ".active" / f"{pack_id}.json"
    if active.is_file():
        try:
            revision = json.loads(active.read_text(encoding="utf-8"))["revision"]
            if _is_sha256(revision):
                short = root / ".revisions" / pack_id / revision[:24]
                full = root / ".revisions" / pack_id / revision
                return full if full.is_dir() and not short.exists() else short
        except (OSError, ValueError, KeyError, TypeError):
            pass
    legacy = root / pack_id
    previous_root = os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT", "")
    if previous_root and not legacy.exists():
        previous = Path(previous_root) / PACKS_DIR_NAME
        try:
            revision = json.loads((previous / ".active" / f"{pack_id}.json").read_text())["revision"]
            if _is_sha256(revision):
                short = previous / ".revisions" / pack_id / revision[:24]
                full = previous / ".revisions" / pack_id / revision
                return full if full.is_dir() and not short.exists() else short
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if (previous / pack_id).is_dir():
            return previous / pack_id
    old = install_root() / PACKS_DIR_NAME / pack_id
    return old if not legacy.exists() and old.is_dir() else legacy


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
    """Встроенный каталог авторитетен; явное зеркало используется только после валидации."""
    with _cache_lock:
        if not force and _manifest_cache["data"] is not None:
            return _manifest_cache["data"]
    override = os.environ.get(MANIFEST_ENV, "").strip()
    if override:
        fetched = _fetch_manifest(override)
        if fetched is not None:
            if fetched.get("schema") not in (1, 2) or not all(
                    isinstance(raw, dict) and _pack_from_dict(raw) is not None for raw in fetched["packs"]):
                raise ValueError("Неверный каталог компонентов")
            with _cache_lock:
                _manifest_cache["data"] = fetched
            return fetched
        raise RuntimeError("Не удалось получить явно заданный каталог компонентов")
    path = bundled_manifest_path()
    bundled = _read_manifest_file(path) if path else None
    if bundled is None:
        bundled = {"schema": 2, "app": __version__, "packs": []}
    with _cache_lock:
        _manifest_cache["data"] = bundled
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
        mirrors = item.get("mirrors", [])
        if not isinstance(mirrors, list) or not all(isinstance(u, str) for u in mirrors):
            raise ValueError("некорректные зеркала")
        files.append(WheelFile(name=name, url=url, sha256=sha, size_bytes=size, mirrors=tuple(mirrors)))
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
        check=str(raw.get("check") or ""),
        unpacked_bytes=int(raw.get("unpacked_bytes") or 0),
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
    """Проверенные активные ревизии и прежние каталоги без скрытого переноса."""
    roots = {runtime_root(), install_root() / PACKS_DIR_NAME}
    if os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT"):
        roots.add(Path(os.environ["ILT_COMPONENT_PREVIOUS_ROOT"]) / PACKS_DIR_NAME)
    ids = set()
    for root in roots:
        if not root.is_dir():
            continue
        ids.update(p.name for p in root.iterdir()
                   if p.is_dir() and not p.name.startswith(".") and not p.name.endswith(TMP_SUFFIX))
        ids.update(p.stem for p in (root / ".active").glob("*.json"))
    return sorted(pack_id for pack_id in ids if is_installed(pack_id))

def _installed_dir_ok(directory: Path) -> bool:
    """Быстрая проверка маркера: inventory сверяется только в verify()."""
    # shortcut: готовность доверяет маркеру; повреждение ловит ручной verify().
    marker = directory / MARKER_NAME
    if not marker.is_file() or not (directory / "site-packages").is_dir():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("id"):
            return False
        return data.get("checked") is not False
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _verify_inventory(directory: Path) -> tuple[bool, str]:
    if not _installed_dir_ok(directory):
        return False, "маркер установки отсутствует"
    try:
        data = json.loads((directory / MARKER_NAME).read_text(encoding="utf-8"))
        inventory = data.get("inventory")
        if inventory is None:
            return True, ""
        if not isinstance(inventory, dict) or not inventory:
            return False, "пустой inventory"
        site = directory / "site-packages"
        for name, info in inventory.items():
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or ":" in name or "\\" in name:
                return False, f"недопустимый путь {name}"
            path = site.joinpath(*pure.parts)
            if not path.is_file() or path.stat().st_size != info["size"]:
                return False, f"повреждён файл {name}"
            if downloads.digest(path) != info["sha256"]:
                return False, f"не совпал sha256 файла {name}"
        return True, ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, str(exc)


def matches(pack: Pack) -> bool:
    """Совпадает состав, а не только имя установленного компонента."""
    directory = pack_dir(pack.id)
    if not _installed_dir_ok(directory):
        return False
    try:
        data = json.loads((directory / MARKER_NAME).read_text(encoding="utf-8"))
        if data.get("revision"):
            return data["revision"] == pack.revision
        if pack.files:
            return data.get("files") == {f.name: f.sha256 for f in pack.files}
        return data.get("version") == pack.version and data.get("sha256") == pack.sha256
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ready(pack: Pack) -> bool:
    if not matches(pack):
        return False
    if not pack.check:
        return True
    from src.app.component_check import requirements_ok

    try:
        data = json.loads((pack_dir(pack.id) / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return requirements_ok(data)


def verify(pack: Pack) -> dict:
    """Полная проверка установленного пака: inventory, затем probe."""
    if not matches(pack):
        return {"ok": False, "kind": "missing", "error": "компонент не установлен"}
    directory = pack_dir(pack.id)
    ok, error = _verify_inventory(directory)
    if not ok:
        return {"ok": False, "kind": "integrity", "error": error}
    if pack.check:
        try:
            from src.app.component_check import probe

            probe({"kind": pack.check, "site": str(directory / "site-packages")})
        except Exception as exc:
            return {"ok": False, "kind": "compatibility", "error": str(exc)}
    from src.app.component_check import COMPONENT_REQUIREMENTS

    try:
        marker = json.loads((directory / MARKER_NAME).read_text(encoding="utf-8"))
        marker["requirements"] = COMPONENT_REQUIREMENTS
        downloads.atomic_json(directory / MARKER_NAME, marker)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"ok": True, "kind": "", "error": ""}


def invalidate(pack: Pack) -> None:
    """Пометить пак неустановленным, сохранив файлы для переустановки из кэша."""
    try:
        (pack_dir(pack.id) / MARKER_NAME).unlink()
    except FileNotFoundError:
        pass


def selected_torch_id(ids: list[str] | None = None) -> str | None:
    """Проверенный установленный пак ещё должен быть выбран для следующего worker."""
    ids = installed_ids() if ids is None else ids
    roots = [runtime_root()]
    if os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT"):
        roots.append(Path(os.environ["ILT_COMPONENT_PREVIOUS_ROOT"]) / PACKS_DIR_NAME)
    for root in roots:
        try:
            selected = json.loads((root / ".active" / "torch.json").read_text())["id"]
            if selected in ids:
                return selected
        except (OSError, ValueError, KeyError):
            pass
    return max((i for i in ids if i.startswith("torch-")), key=lambda i: _ACTIVATION_ORDER.get(i, -1), default=None)

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
    if not _installed_dir_ok(directory):
        return False
    try:
        marker = json.loads((directory / MARKER_NAME).read_text(encoding="utf-8"))
        if marker.get("python") and marker["python"] != python_tag():
            return False
        if marker.get("platform") and marker["platform"] != platform_tag():
            return False
        native = re.findall(r"-cp(\d+)-cp\d+-", " ".join(marker.get("files", {})))
        return not native or all(tag == python_tag() for tag in native)
    except (OSError, ValueError, TypeError):
        return False


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
                "state": "installed" if ready(pack) else "available",
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
    """Статус из чистой проверки: parent-sidecar не импортирует и не блокирует torch DLL."""
    already = sys.modules.get("torch")
    if already is not None:
        try:
            return True, bool(already.cuda.is_available())
        except Exception:
            return True, False
    ids = installed_ids()
    chosen = selected_torch_id(ids)
    if chosen is not None:
        ids = [chosen]
    for pack_id in reversed(sorted(ids, key=lambda x: _ACTIVATION_ORDER.get(x, 9))):
        if not pack_id.startswith("torch-"):
            continue
        try:
            data = json.loads((pack_dir(pack_id) / MARKER_NAME).read_text(encoding="utf-8"))
            if data.get("checked"):
                return True, bool(data.get("cuda"))
        except (OSError, ValueError):
            pass
    return False, False

def argos_ready() -> bool:
    """Argos импортируется (пак установлен или dev-venv). Без импорта самого пакета."""
    if is_installed("argos"):
        return True
    try:
        return importlib.util.find_spec("argostranslate") is not None
    except (ImportError, ValueError):
        return False


def download_and_install(pack: Pack | str, progress=None, retries: int = 3, pause=None) -> Path:
    """Проверить новую ревизию до атомарного переключения; кэш сохраняется при любом сбое."""
    if isinstance(pack, str):
        pack = pack_by_id(pack)
    with downloads.installer_lock():
        if matches(pack):
            directory = pack_dir(pack.id)
            marker = json.loads((directory / MARKER_NAME).read_text(encoding="utf-8"))
            from src.app.component_check import requirements_ok

            if pack.check and not requirements_ok(marker):
                from src.app.component_check import probe

                checked = probe({"kind": pack.check, "site": str(directory / "site-packages")})
                _write_marker(directory, pack, checked)
            if pack.kind == "torch":
                downloads.atomic_json(runtime_root() / ".active" / "torch.json", {"id": pack.id})
            _notify(progress, pack.effective_size, pack.effective_size, "installed", "уже установлено")
            return directory
        root = runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        revision_root = root / ".revisions" / pack.id
        destination = revision_root / pack.revision[:24]
        temporary = revision_root / f"{pack.revision[:24]}.tmp"
        staging = root / f"{pack.id}{WHEELS_PART_SUFFIX}"
        archive = root / f"{pack.id}{PART_SUFFIX}"
        checked = {}
        try:
            if pack.is_wheels:
                _download_files(pack, staging, progress, retries, pause)
                needed = sum(info.file_size for wheel in pack.files
                             for info in zipfile.ZipFile(staging / wheel.name).infolist())
                downloads.ensure_space(revision_root, needed)
            else:
                _download_pack(pack, archive, progress, retries)
                downloads.ensure_space(revision_root, pack.unpacked_bytes or pack.effective_size * 4)
            downloads.check_pause(pause)
            _notify(progress, pack.effective_size, pack.effective_size, "installing", "распаковка")
            if pack.is_wheels:
                _extract_wheels(pack, staging, temporary)
            else:
                _extract_pack(pack, archive, temporary)
            _notify(progress, pack.effective_size, pack.effective_size, "checking", "проверка компонента")
            if pack.check:
                from src.app.component_check import probe

                checked = probe({"kind": pack.check, "site": str(temporary / "site-packages")})
            _write_marker(temporary, pack, checked)
            downloads.check_pause(pause)
            if destination.exists():
                if _installed_dir_ok(destination):
                    if json.loads((destination / MARKER_NAME).read_text())["revision"] != pack.revision:
                        raise RuntimeError("Конфликт каталога ревизии компонента")
                    shutil.rmtree(temporary)
                else:
                    previous = destination.with_name(destination.name + ".old")
                    if previous.exists():
                        raise RuntimeError("Перезапустите приложение для завершения восстановления")
                    destination.replace(previous)
                    try:
                        temporary.replace(destination)
                    except Exception:
                        previous.replace(destination)
                        raise
                    shutil.rmtree(previous, ignore_errors=True)
            else:
                temporary.replace(destination)
            downloads.atomic_json(root / ".active" / f"{pack.id}.json", {"revision": pack.revision, "activated_at": time.time()})
            if pack.kind == "torch":
                downloads.atomic_json(root / ".active" / "torch.json", {"id": pack.id})
            if not sys.modules.get("torch"):
                activate_path(destination)
            _notify(progress, pack.effective_size, pack.effective_size, "installed", "")
            return destination
        finally:
            archive.unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

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


def _download_files(pack: Pack, staging: Path, progress, retries: int, pause=None) -> None:
    """Staging — ссылки на проверенный постоянный кэш, не источник восстановления."""
    staging.mkdir(parents=True, exist_ok=True)
    done = 0
    for wheel in pack.files:
        item = downloads.Artifact(wheel.name, (wheel.url, *wheel.mirrors), wheel.sha256, wheel.size_bytes)
        ready = downloads.fetch(item, progress=lambda n, _t: _notify(
            progress, done + n, pack.effective_size, "downloading", ""), pause=pause, retries=retries)
        target = staging / wheel.name
        target.unlink(missing_ok=True)
        try:
            os.link(ready, target)
        except OSError:
            shutil.copyfile(ready, target)
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
            if os.name == "nt" and target.suffix.lower() in (".dll", ".pyd") and len(str(target.resolve())) >= 248:
                raise PermissionError("Путь к компонентам слишком длинный. Выберите более короткую папку.")
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


def _write_marker(directory: Path, pack: Pack, checked: dict | None = None) -> None:
    site = directory / "site-packages"
    inventory = {}
    for path in site.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            stat = path.stat()
            inventory[path.relative_to(site).as_posix()] = {
                "size": stat.st_size, "mtime": stat.st_mtime_ns, "sha256": downloads.digest(path)}
    from src.app.component_check import COMPONENT_REQUIREMENTS

    payload = {"id": pack.id, "version": pack.version, "revision": pack.revision,
               "python": pack.python, "platform": pack.platform,
               "installed_at": time.time(), "inventory": inventory, "checked": True,
               "requirements": COMPONENT_REQUIREMENTS, "cuda": bool((checked or {}).get("cuda"))}
    if pack.is_wheels:
        payload.update(format="wheels", files={f.name: f.sha256 for f in pack.files})
    else:
        payload.update(format="archive", sha256=pack.sha256)
    downloads.atomic_json(directory / MARKER_NAME, payload)

def remove(pack_id: str, packs_root: Path | None = None) -> bool:
    """Удалить пак. False — папки не было (идемпотентно).

    На Windows загруженные DLL (torch) держат файлы, и полный ``rmtree``
    падает. Тогда каталог переименовывается в ``<id>.tmp`` (rename разрешён
    при открытых файлах) и дочищается при следующем старте (``activate``).
    """
    root = Path(packs_root) if packs_root is not None else runtime_root()
    pack_id = _safe_id(pack_id)
    if packs_root is None:
        previous = os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT", "")
        roots = {root, install_root() / PACKS_DIR_NAME}
        if previous:
            roots.add(Path(previous) / PACKS_DIR_NAME)
        removed = False
        with downloads.installer_lock():
            for candidate in roots:
                revisions = candidate / ".revisions" / pack_id
                active = candidate / ".active" / f"{pack_id}.json"
                if active.exists() or revisions.exists():
                    active.unlink(missing_ok=True)
                    choice = candidate / ".active" / "torch.json"
                    try:
                        if json.loads(choice.read_text())["id"] == pack_id:
                            choice.unlink()
                    except (OSError, ValueError, KeyError):
                        pass
                    if revisions.exists():
                        graveyard = candidate / f"{pack_id}{TMP_SUFFIX}"
                        shutil.rmtree(graveyard, ignore_errors=True)
                        revisions.replace(graveyard)
                        shutil.rmtree(graveyard, ignore_errors=True)
                    removed = True
                removed = remove(pack_id, candidate) or removed
        return removed
    active = root / ".active" / f"{pack_id}.json"
    if active.is_file():
        with downloads.installer_lock():
            directory = pack_dir(pack_id)
            active.unlink()
            choice = root / ".active" / "torch.json"
            try:
                if json.loads(choice.read_text())["id"] == pack_id:
                    choice.unlink()
            except (OSError, ValueError, KeyError):
                pass
            graveyard = directory.with_name(directory.name + TMP_SUFFIX)
            try:
                directory.replace(graveyard)
                shutil.rmtree(graveyard, ignore_errors=True)
            except OSError:
                logger.info("Удаление ревизии завершится после перезапуска")
            return True
    directory = root / _safe_id(pack_id)
    if not directory.is_dir():
        return False
    try:
        shutil.rmtree(directory)
    except OSError:
        graveyard = root / f"{_safe_id(pack_id)}{TMP_SUFFIX}"
        if graveyard.exists():
            shutil.rmtree(graveyard, ignore_errors=True)
        try:
            directory.replace(graveyard)
        except OSError:
            logger.warning("Не удалось убрать каталог %s", directory, exc_info=True)
            raise
        shutil.rmtree(graveyard, ignore_errors=True)
        logger.info("Каталог %s занят процессом: место освободит перезапуск", directory)
    torch_state(refresh=True)
    return True


def _cleanup_stale_temp(root: Path) -> None:
    """Убрать остатки ``*.tmp``: неудачные установки и отложенные удаления."""
    for entry in root.glob(f"*{TMP_SUFFIX}"):
        try:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            logger.debug("Не убрался временный каталог %s", entry, exc_info=True)


def configure_argos_paths() -> None:
    """Все служебные папки Argos принадлежат приложению, включая portable."""
    from src.app.paths import data_root

    for key, folder in (("XDG_DATA_HOME", "share"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
        os.environ.setdefault(key, str(data_root() / "libraries" / folder))
    os.environ.setdefault("ARGOS_PACKAGES_DIR", str(data_root() / "argos-packages"))
    os.environ.setdefault("ARGOS_TRANSLATE_PACKAGE_DIR", str(data_root() / "argos-packages"))
    os.environ["ARGOS_CHUNK_TYPE"] = "MINISBD"


def startup() -> list[str]:
    """Старт процесса: активация паков и ``ARGOS_PACKAGES_DIR``.

    Вызывается из ``src/app/__main__.py`` и из ``worker_main`` (spawn-ребёнок
    не проходит через main) до первого импорта torch/argostranslate.
    """
    if getattr(sys, "frozen", False) and not os.environ.get("ILT_COMPONENT_ROOT"):
        from src.app.paths import settings_path
        from src.app.settings import AppSettings

        settings, _warnings = AppSettings.load(settings_path())
        if settings.components_dir:
            os.environ["ILT_COMPONENT_ROOT"] = settings.components_dir
        if settings.components_previous_dir:
            os.environ["ILT_COMPONENT_PREVIOUS_ROOT"] = settings.components_previous_dir
    activated = activate()
    configure_argos_paths()
    try:
        from src.app.paths import data_root

        os.environ.setdefault("ARGOS_PACKAGES_DIR", str(data_root() / "argos-packages"))
        os.environ.setdefault("ARGOS_TRANSLATE_PACKAGE_DIR", str(data_root() / "argos-packages"))
    except Exception:
        logger.debug("Не удалось задать ARGOS_PACKAGES_DIR", exc_info=True)
    return activated


def activation_signature() -> str:
    """Изменение указателей поднимает новый worker перед следующим заданием."""
    entries = []
    root = runtime_root()
    for path in sorted((root / ".active").glob("*.json")):
        entries.append((path.name, path.read_text(encoding="utf-8")))
    from src.app.component_catalog import store_root

    for path in sorted((store_root() / ".active").glob("*.json")):
        entries.append((path.name, path.read_text(encoding="utf-8")))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def activate(packs_root: Path | None = None) -> list[str]:
    """Выбрать один torch до импорта DLL, затем подключить остальные компоненты."""
    _attach_stdlib()
    root = Path(packs_root) if packs_root is not None else runtime_root()
    if not root.is_dir() and packs_root is not None:
        return []
    _cleanup_stale_temp(root)
    if packs_root is not None:
        ids = [p.name for p in root.iterdir() if p.is_dir() and _installed_dir_ok(p)]
        directories = {i: root / i for i in ids}
    else:
        ids = installed_ids()
        directories = {i: pack_dir(i) for i in ids}
    torch_ids = [i for i in ids if i.startswith("torch-")]
    chosen = selected_torch_id(ids) if packs_root is None else None
    try:
        chosen = json.loads((root / ".active" / "torch.json").read_text())["id"]
    except (OSError, ValueError, KeyError):
        pass
    if chosen not in torch_ids:
        chosen = max(torch_ids, key=lambda i: _ACTIVATION_ORDER.get(i, -1), default=None)
    ids = [i for i in ids if not i.startswith("torch-") or i == chosen]
    activated = []
    for pack_id in sorted(ids, key=lambda i: _ACTIVATION_ORDER.get(i, 9)):
        if activate_path(directories[pack_id]):
            activated.append(pack_id)
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
    candidates = [site / "torch" / "lib", site / "ctranslate2"]
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS))
    library_dirs = [path for path in candidates if path.is_dir()]
    if not library_dirs or not hasattr(os, "add_dll_directory"):
        return
    for library in library_dirs:
        text = str(library)
        try:
            if text not in _dll_handles:
                _dll_handles[text] = os.add_dll_directory(text)
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
        self._lock = threading.RLock()
        self._state: dict = {"id": "", "state": "idle", "done": 0, "total": 0, "error": ""}
        self._thread: threading.Thread | None = None

    def current(self) -> dict:
        with self._lock:
            return dict(self._state)

    def busy(self) -> bool:
        with self._lock:
            return bool(self._thread is not None and self._thread.is_alive()) or self._state["state"] in ("downloading", "installing", "checking")

    def start(self, pack_id: str) -> dict:
        """Резервирование и запуск сериализованы, включая параллельные HTTP-запросы."""
        with self._lock:
            if self.busy():
                return dict(self._state)
            pack = pack_by_id(pack_id)
            if ready(pack) and (pack.kind != "torch" or selected_torch_id() == pack.id):
                return {"id": pack.id, "state": "installed", "done": 0, "total": 0, "error": ""}
            self._update({"id": pack.id, "state": "downloading", "done": 0, "total": 0, "error": ""})
            self._thread = threading.Thread(target=self._run, args=(pack,), name="ilt-runtime", daemon=True)
            self._thread.start()
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
