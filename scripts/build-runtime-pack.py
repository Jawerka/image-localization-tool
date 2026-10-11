"""DEPRECATED (specs/032-runtime-wheelset): legacy .7z-сборка паков.

Рантайм ставится из официальных колёс (``scripts/build_runtime_locks.py``);
этот скрипт оставлен для пересборки старых архивных паков.

Собрать .7z-пак рантайма из чистого venv (``site-packages``).

Пак — архив с каталогом ``site-packages`` в корне: torch с зависимостями или
argostranslate со стеком. Лишнее вырезается (кэш, заголовки, тесты, стабы,
``.lib``), архив сжимается LZMA2, sha256 и размер пишутся в ``packs.json``
рядом с архивами. Манифест релиза собирает ``scripts/build-runtime-manifest.py``.

Запуск (py7zr нужен интерпретатору, который запускает скрипт):
    python scripts/build-runtime-pack.py --venv build/runtime-venvs/torch-cpu \\
        --kind torch --variant cpu --platform win --out dist/packs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACK_TITLES = {
    "torch-cpu": "PyTorch CPU (LaMa)",
    "torch-cu128": "PyTorch CUDA 12.8 (NVIDIA)",
    "argos": "Argos Translate (офлайн-перевод)",
}
DRIVER_MIN = {"torch-cu128": 570}

# Каталоги и файлы, которые не нужны рантайму.
SKIP_DIR_NAMES = {"__pycache__", "test", "tests", "include"}
SKIP_TOP_NAMES = {
    "pip",
    "wheel",
    "setuptools",
    "pkg_resources",
    "_distutils_hack",
    "easy_install.py",
    "distutils-precedence.pth",
}
SKIP_SUFFIXES = {
    ".lib",
    ".exp",
    ".pdb",
    ".pyi",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".a",
    ".o",
    ".obj",
}


def site_packages_path(venv: Path) -> Path:
    """Каталог site-packages внутри venv (Windows и POSIX)."""
    venv = Path(venv)
    windows = venv / "Lib" / "site-packages"
    if windows.is_dir():
        return windows
    matches = sorted((venv / "lib").glob("python*/site-packages"))
    if matches:
        return matches[0]
    raise SystemExit(f"Нет site-packages в venv: {venv}")


def pack_id(kind: str, variant: str) -> str:
    if kind == "torch":
        if variant not in ("cpu", "cu128"):
            raise SystemExit(f"Неизвестный вариант torch: {variant}")
        return f"torch-{variant}"
    if kind == "argos":
        return "argos"
    raise SystemExit(f"Неизвестный тип пака: {kind}")


def should_skip(relative: Path) -> bool:
    """Пропустить служебный мусор и заголовки внутри site-packages."""
    parts = relative.parts
    if any(part in SKIP_DIR_NAMES for part in parts[:-1]):
        return True
    top = parts[0] if parts else ""
    if top in SKIP_TOP_NAMES or top.startswith(("pip-", "setuptools-", "wheel-")):
        return True
    suffix = relative.suffix.casefold()
    if suffix in SKIP_SUFFIXES:
        return True
    return False


def stage_site_packages(site: Path, stage_root: Path) -> int:
    """Скопировать нужное из site-packages в ``<stage>/site-packages``."""
    target = stage_root / "site-packages"
    if target.exists():
        shutil.rmtree(target)
    copied = 0
    for path in sorted(site.rglob("*")):
        relative = path.relative_to(site)
        if path.is_dir():
            continue
        if should_skip(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def write_archive(archive: Path, stage_root: Path) -> None:
    """LZMA2-архив с относительными путями от ``stage_root``."""
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Нужен py7zr: pip install py7zr") from exc
    filters = [{"id": py7zr.FILTER_LZMA2, "preset": 9}]
    with py7zr.SevenZipFile(archive, "w", filters=filters) as handle:
        for path in sorted(stage_root.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(stage_root).as_posix())


def detect_version(venv: Path, kind: str) -> str:
    """Версия установленного пака из его venv (best-effort)."""
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if kind == "torch":
        snippet = "import torch; print(torch.__version__)"
    else:
        snippet = "import importlib.metadata as m; print(m.version('argostranslate'))"
    try:
        result = subprocess.run(
            [str(python), "-c", snippet],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return (result.stdout or "").strip() or "unknown"


def build_pack(
    venv: Path,
    kind: str,
    variant: str,
    platform: str,
    out_dir: Path,
    *,
    version: str = "",
    python_tag: str = "",
    stage_root: Path | None = None,
) -> dict:
    """Собрать архив и вернуть запись для ``packs.json``."""
    venv = Path(venv)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    identifier = pack_id(kind, variant)
    tag = python_tag or f"{sys.version_info.major}{sys.version_info.minor}"
    version = version or detect_version(venv, kind)
    name = f"ilt-runtime-{identifier}-{platform}-x64-py{tag}.7z"
    archive = out_dir / name

    stage = Path(stage_root) if stage_root is not None else ROOT / "build" / "pack-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    copied = stage_site_packages(site_packages_path(venv), stage)
    write_archive(archive, stage)
    shutil.rmtree(stage, ignore_errors=True)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    record = {
        "id": identifier,
        "title": PACK_TITLES[identifier],
        "kind": kind,
        "os": platform,
        "arch": "x64",
        "python": tag,
        "version": version,
        "file": name,
        "sha256": digest,
        "size_bytes": archive.stat().st_size,
    }
    if identifier in DRIVER_MIN:
        record["driver_min"] = DRIVER_MIN[identifier]
    print(f"{name}: файлов {copied}, {record['size_bytes'] / 1e6:.1f} МБ, sha256 {digest[:12]}…")
    return record


def update_summary(out_dir: Path, record: dict) -> Path:
    """Добавить/заменить запись в ``packs.json``."""
    summary_path = Path(out_dir) / "packs.json"
    entries: list[dict] = []
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = [item for item in data if isinstance(item, dict)]
        except (OSError, UnicodeError, json.JSONDecodeError):
            entries = []
    key = (record.get("id"), record.get("os"))
    entries = [item for item in entries if (item.get("id"), item.get("os")) != key]
    entries.append(dict(record))
    entries.sort(key=lambda item: (str(item.get("os")), str(item.get("id"))))
    summary_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка .7z-пака рантайма")
    parser.add_argument("--venv", required=True, help="чистый venv с паком")
    parser.add_argument("--kind", required=True, choices=["torch", "argos"])
    parser.add_argument("--variant", default="cpu", help="cpu | cu128 (для torch)")
    parser.add_argument("--platform", required=True, choices=["win", "linux"])
    parser.add_argument("--out", default="dist/packs", help="каталог для .7z")
    parser.add_argument("--version", default="", help="версия пака (иначе из venv)")
    parser.add_argument("--python-tag", default="", help="тег Python (иначе текущий)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    record = build_pack(
        Path(args.venv),
        args.kind,
        args.variant if args.kind == "torch" else "",
        args.platform,
        out_dir,
        version=args.version,
        python_tag=args.python_tag,
    )
    summary = update_summary(out_dir, record)
    print(f"Сводка: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
