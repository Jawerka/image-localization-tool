"""Определение GPU и рекомендация компонентов рантайма.

NVIDIA опознаётся через ``nvidia-smi`` (имя и версия драйвера). Порог
CUDA-пакета cu128 — драйвер 570 и новее (RTX 20–50). AMD/Intel и машины без
NVIDIA получают CPU-пакет: ускорение в 1.0.0 для них не собирается. Все
внешние команды ограничены таймаутом и не роняют приложение.
"""

from __future__ import annotations

import re
import subprocess
import sys

DRIVER_MIN = 570
DRIVER_MIN_CU130 = 580

_NVIDIA_QUERY = [
    "nvidia-smi",
    "--query-gpu=name,driver_version",
    "--format=csv,noheader",
]
_POWERSHELL_GPUS = [
    "powershell",
    "-NoProfile",
    "-Command",
    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
]
_WMIC_GPUS = ["wmic", "path", "win32_VideoController", "get", "name"]

_cache: dict | None = None


def parse_nvidia_smi(text: str) -> list[dict]:
    """Строки ``Имя, 617.14`` → ``{vendor, name, driver}``."""
    gpus: list[dict] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        name, _, driver = line.partition(",")
        name = name.strip()
        driver = driver.strip()
        if not name or "not found" in name.casefold():
            continue
        gpus.append({"vendor": "nvidia", "name": name, "driver": driver})
    return gpus


def driver_major(value) -> int | None:
    """``617.14`` → ``617``. Не число — None."""
    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def classify_vendor(name: str) -> str:
    low = str(name or "").casefold()
    if "nvidia" in low:
        return "nvidia"
    if "amd" in low or "radeon" in low:
        return "amd"
    if "intel" in low:
        return "intel"
    return "other"


def parse_vendor_names(text: str) -> list[str]:
    """Строки вывода WMI/lspci → имена GPU без заголовков."""
    names: list[str] = []
    for line in str(text or "").splitlines():
        value = line.strip()
        if not value or value.casefold() in ("name", "name "):
            continue
        if value.startswith("Name"):
            continue
        names.append(value)
    return names


def detect(refresh: bool = False) -> dict:
    """Снимок железа: vendor/name/driver/recommended/reason/gpus. Кэш на процесс."""
    global _cache
    if _cache is not None and not refresh:
        return dict(_cache)
    gpus = _detect_gpus()
    recommended, reason = _recommend(gpus)
    main = next((gpu for gpu in gpus if gpu["vendor"] == "nvidia"), gpus[0] if gpus else {})
    _cache = {
        "vendor": str(main.get("vendor") or "none"),
        "name": str(main.get("name") or ""),
        "driver": driver_major(main.get("driver")) if main.get("driver") else None,
        "recommended": recommended,
        "reason": reason,
        "gpus": gpus,
    }
    return dict(_cache)


def _detect_gpus() -> list[dict]:
    gpus: list[dict] = []
    smi = _run(_NVIDIA_QUERY, timeout=5)
    if smi:
        gpus.extend(parse_nvidia_smi(smi))
    seen_nvidia = bool(gpus)
    for name in _other_gpu_names():
        vendor = classify_vendor(name)
        if vendor == "nvidia" and seen_nvidia:
            continue
        gpus.append({"vendor": vendor, "name": name, "driver": ""})
    return gpus


def _other_gpu_names() -> list[str]:
    if sys.platform == "win32":
        text = _run(_POWERSHELL_GPUS, timeout=8)
        if text is None:
            text = _run(_WMIC_GPUS, timeout=8)
        return parse_vendor_names(text or "")
    if sys.platform.startswith("linux"):
        text = _run(["lspci"], timeout=8)
        if not text:
            return []
        names = []
        for line in text.splitlines():
            low = line.casefold()
            if "vga compatible controller" not in low and "3d controller" not in low:
                continue
            _, _, tail = line.partition(": ")
            names.append(tail.strip() or line.strip())
        return names
    return []


def _run(command: list[str], timeout: float) -> str | None:
    """Запустить команду; ошибки и таймаут — None."""
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def _recommend(gpus: list[dict]) -> tuple[str, str]:
    nvidia = next((gpu for gpu in gpus if gpu["vendor"] == "nvidia"), None)
    if nvidia is not None:
        major = driver_major(nvidia.get("driver"))
        name = str(nvidia.get("name") or "NVIDIA GPU")
        if major is None:
            return "torch-cpu", f"{name}: версия драйвера неизвестна — CPU"
        if sys.platform != "win32":
            return "torch-cpu", f"{name}: для этой платформы доступен CPU-компонент"
        if major >= DRIVER_MIN_CU130 and sys.platform == "win32":
            return "torch-cu130", f"CUDA доступна: драйвер {major} ≥ {DRIVER_MIN_CU130} ({name})"
        if major >= DRIVER_MIN and sys.platform == "win32":
            return "torch-cu128", f"CUDA доступна: драйвер {major} ≥ {DRIVER_MIN} ({name})"
        return "torch-cpu", (
            f"драйвер {major} < {DRIVER_MIN}: обновите драйвер NVIDIA для CUDA или CPU"
        )
    if gpus:
        vendor = {"amd": "AMD", "intel": "Intel"}.get(gpus[0]["vendor"], "GPU")
        return "torch-cpu", f"{vendor}: ускорение в 1.0.0 не поддерживается — CPU"
    return "torch-cpu", "NVIDIA не найдена — только CPU"
