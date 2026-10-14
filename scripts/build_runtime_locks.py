"""Скачать официальные колёса рантайма и собрать лок-сводку (schema 2).

Шаги pip без установки:

1. ``pip install --dry-run --ignore-installed --report resolve.json`` — резолв
   зависимостей, точные пины и официальные url (+sha256, если индекс отдал) —
   CI не ставит torch в venv;
2. ``pip download --only-binary=:all: --no-deps -d stage`` — колёса; sha256
   файла сверяется с отчётом, если индекс отдал хэш, иначе считается по
   скачанному файлу.

``argostranslate`` — особый случай: PyPI-релиз 1.11.0 жёстко требует
stanza→torch (argos-пак стал бы ~216 МБ с torch), поэтому колесо собирается
из официального git-коммита (там stanza — optional extra) и публикуется одним
ассетом релиза; CI передаёт готовое колесо через ``--hosted-wheel``.

Рядом со сводкой ``<out>/<id>-<os>.json`` пишется полный freeze
``py310-<id>-<os>.lock`` (с ``--lock-dir`` — в репозиторий ``locks/``,
стиль AUTOMATIC1111: пин-файлы ревьюятся в PR и проверяются CI).

Запуск:
    python scripts/build_runtime_locks.py --pack torch-cpu --os win
    python scripts/build_runtime_locks.py --pack argos --os linux --hosted-wheel <whl>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.smoke_dist import read_app_version  # noqa: E402
from src.app.runtime import RELEASE_BASE  # noqa: E402

PACK_TITLES = {
    "torch-cpu": "PyTorch CPU (LaMa)",
    "torch-cu128": "PyTorch CUDA 12.8 (NVIDIA)",
    "torch-cu130": "PyTorch CUDA 13.0 (NVIDIA)",
    "argos": "Argos Translate (офлайн-перевод)",
}
KIND = {"torch-cpu": "torch", "torch-cu128": "torch", "torch-cu130": "torch", "argos": "argos"}
DRIVER_MIN = {"torch-cu128": 570, "torch-cu130": 580}
WHEEL_BASE = "https://raw.githubusercontent.com/Jawerka/image-localization-tool/cbe2960b7d620cbc0348f50ba325e8945384d795/assets"

TORCH_VERSION = "2.11.0"
# argostranslate из официального git: в 1.11.1 stanza стал optional extra,
# PyPI-релизы (1.9.6…1.11.0) тянут stanza→torch жёстко.
ARGOS_GIT_URL = "https://github.com/argosopentech/argos-translate.git"
ARGOS_COMMIT = "17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88"
PYPI_INDEX = "https://pypi.org/simple"
TORCH_INDEX = {
    "torch-cpu": "https://download.pytorch.org/whl/cpu",
    "torch-cu128": "https://download.pytorch.org/whl/cu128",
    "torch-cu130": "https://download.pytorch.org/whl/cu130",
}
TOP_PACKAGE = {key: ("argostranslate" if key == "argos" else "torch") for key in KIND}

APP_VERSION = read_app_version(ROOT)


def _is_sha256(text: str) -> bool:
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def _pack_spec(pack: str) -> tuple[str, list[str]]:
    """Верхнеуровневая спецификация pip и аргументы индексов."""
    if pack == "argos":
        return f"argostranslate @ git+{ARGOS_GIT_URL}@{ARGOS_COMMIT}", []
    return (
        f"torch=={TORCH_VERSION}",
        ["--index-url", TORCH_INDEX[pack], "--extra-index-url", PYPI_INDEX],
    )


def _run_pip(args: list[str]) -> None:
    command = [sys.executable, "-m", "pip", *args]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(
            f"pip завершился с кодом {result.returncode}:\n{result.stdout}\n{result.stderr}"
        )


def _load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Не читается отчёт pip {path}: {exc}") from exc


def _name_version_from_url(url: str) -> tuple[str, str]:
    """Запасной разбор ``name-version`` из имени колеса, если нет metadata."""
    name = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    if not name.endswith(".whl"):
        return "", ""
    parts = name[:-4].split("-")
    if len(parts) < 5:
        return "", ""
    return parts[0], parts[1]


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_pins(pack: str, work: Path) -> tuple[list[str], list[str], str, dict[str, dict]]:
    """Резолв без установки.

    Возвращает: пины для лок-файла (все), пины для скачивания (без VCS),
    версию верхнего пакета и карту ожиданий ``имя колеса → {url, sha256}``.
    """
    spec, index_args = _pack_spec(pack)
    report = work / "resolve.json"
    _run_pip(
        [
            "install",
            "--dry-run",
            "--ignore-installed",
            "--quiet",
            "--report",
            str(report),
            spec,
            *index_args,
        ]
    )
    data = _load_report(report)
    versions: dict[str, str] = {}
    vcs_names: set[str] = set()
    expected: dict[str, dict] = {}
    for item in data.get("install") or []:
        metadata = item.get("metadata") or {}
        name = str(metadata.get("name") or "").strip()
        version = str(metadata.get("version") or "").strip()
        info = item.get("download_info") or {}
        url = str(info.get("url") or "")
        if not name or not version:
            name, version = _name_version_from_url(url)
        if name and version:
            versions[name] = version
        if isinstance(info.get("vcs_info"), dict) or url.startswith(("git+", "hg+")):
            if name:
                vcs_names.add(name)
            continue
        file_name = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
        hashes = (info.get("archive_info") or {}).get("hashes") or {}
        sha = str(hashes.get("sha256") or "").strip().casefold()
        if file_name.endswith(".whl") and url.startswith("https://"):
            expected[file_name] = {"url": url, "sha256": sha if _is_sha256(sha) else ""}
    if not versions:
        raise SystemExit(f"Пустой резолв для {pack}")
    lock_pins = [f"{name}=={versions[name]}" for name in sorted(versions, key=str.casefold)]
    download_pins = [
        f"{name}=={versions[name]}"
        for name in sorted(versions, key=str.casefold)
        if name not in vcs_names
    ]
    return lock_pins, download_pins, versions.get(TOP_PACKAGE[pack], "unknown"), expected


def download_wheels(
    pack: str, pins: list[str], stage: Path, expected: dict[str, dict]
) -> list[dict]:
    """Скачать колёса по пинам и собрать ``files[]`` с официальными url/sha256."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    _, index_args = _pack_spec(pack)
    _run_pip(
        [
            "download",
            "--only-binary=:all:",
            "--no-deps",
            "--quiet",
            "--dest",
            str(stage),
            *pins,
            *index_args,
        ]
    )
    wheels = sorted(
        (path for path in stage.iterdir() if path.is_file() and path.suffix == ".whl"),
        key=lambda path: path.name,
    )
    if len(wheels) != len(expected):
        raise SystemExit(f"Файлов {len(wheels)} ≠ ожидалось {len(expected)} для {pack}")
    files: list[dict] = []
    for path in wheels:
        item = expected.get(path.name) or {}
        url = str(item.get("url") or "")
        sha = str(item.get("sha256") or "")
        digest = _file_sha256(path)
        if sha and digest != sha:
            raise SystemExit(f"sha256 файла {path.name} не совпал с индексом")
        if not url:
            raise SystemExit(f"Нет официального URL для {path.name}")
        files.append(
            {
                "name": path.name,
                "url": url,
                "sha256": digest,
                "size_bytes": path.stat().st_size,
            }
        )
    if not files:
        raise SystemExit(f"Ни одного колеса не скачано для {pack}")
    return files


def build_argos_wheel(stage: Path) -> Path:
    """Собрать колесо argostranslate из официального git-пина (stanza optional)."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    spec = f"argostranslate @ git+{ARGOS_GIT_URL}@{ARGOS_COMMIT}"
    _run_pip(["wheel", "--no-deps", "--quiet", "--wheel-dir", str(stage), spec])
    wheels = sorted(path for path in stage.iterdir() if path.suffix == ".whl")
    if len(wheels) != 1:
        raise SystemExit(f"Ожидалось одно колесо argostranslate, найдено {len(wheels)}")
    return wheels[0]


def hosted_entry(path: Path, url_base: str) -> dict:
    """Запись ``files[]`` для собранного колеса, публикуемого ассетом релиза."""
    return {
        "name": path.name,
        "url": f"{url_base.rstrip('/')}/{path.name}",
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def build_record(pack: str, os_tag: str, python_tag: str, version: str, files: list[dict]) -> dict:
    """Запись сводки/манифеста (schema 2, ``format:"wheels"``)."""
    record = {
        "id": pack,
        "title": PACK_TITLES[pack],
        "kind": KIND[pack],
        "os": os_tag,
        "arch": "x64",
        "python": python_tag,
        "version": version,
        "format": "wheels",
        "size_bytes": sum(int(item["size_bytes"]) for item in files),
        "files": files,
    }
    if pack in DRIVER_MIN:
        record["driver_min"] = DRIVER_MIN[pack]
    return record


def update_summary(out_dir: Path, record: dict) -> Path:
    """Добавить/заменить запись в ``packs.json`` (ключ — id+os)."""
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


def lock_text(pack: str, os_tag: str, python_tag: str, pins: list[str]) -> str:
    header = (
        f"# python {python_tag[:1]}.{python_tag[1:]}, {pack}, {os_tag}: "
        f"полный freeze официальных колёс (specs/032-runtime-wheelset)"
    )
    return "\n".join([header, *pins, ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Лок-сводка рантайма из официальных колёс")
    parser.add_argument("--pack", required=True, choices=sorted(PACK_TITLES))
    parser.add_argument("--os", required=True, choices=["win", "linux"], dest="os_tag")
    parser.add_argument("--python-tag", default="", help="по умолчанию — текущий интерпретатор")
    parser.add_argument("--out", default="dist/locks", help="каталог сводок и колёс")
    parser.add_argument("--update-catalog", action="store_true", help="явно обновить locks/runtime-catalog.json после проверки колёс")
    parser.add_argument("--work", default="", help="рабочий каталог (иначе <out>/stage/<id>-<os>)")
    parser.add_argument(
        "--lock-dir",
        default="",
        help="каталог пин-файлов в репозитории (locks/); иначе lock рядом со сводкой",
    )
    parser.add_argument(
        "--wheel-base",
        default=WHEEL_BASE,
        help="база URL для публикуемого колеса argostranslate",
    )
    parser.add_argument(
        "--hosted-wheel",
        default="",
        help="готовое колесо argostranslate (CI); без него колесо собирается из git-пина",
    )
    args = parser.parse_args(argv)
    if args.os_tag != "win" and args.pack in DRIVER_MIN:
        parser.error("CUDA-паки в этой версии поддерживаются только на Windows")

    out_dir = _resolve(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = (
        _resolve(args.work)
        if args.work
        else out_dir / "stage" / f"{args.pack}-{args.os_tag}"
    )
    work.mkdir(parents=True, exist_ok=True)
    python_tag = args.python_tag or f"{sys.version_info.major}{sys.version_info.minor}"

    lock_pins, download_pins, top_version, expected = resolve_pins(args.pack, work)
    files = download_wheels(args.pack, download_pins, work / "wheels", expected)
    if args.pack == "argos":
        if args.hosted_wheel:
            wheel = _resolve(args.hosted_wheel)
            if not wheel.is_file():
                raise SystemExit(f"Нет колеса argostranslate: {wheel}")
        else:
            wheel = build_argos_wheel(work / "wheel")
        files.append(hosted_entry(wheel, args.wheel_base))
        files.sort(key=lambda item: item["name"])
        # Колесо для публикации — рядом со сводкой (publish-release ищет *.whl там).
        target = out_dir / wheel.name
        if wheel.resolve() != target.resolve():
            shutil.copy2(wheel, target)
            print(f"Колесо для релиза: {target}")

    record = build_record(args.pack, args.os_tag, python_tag, top_version, files)
    if args.update_catalog:
        import zipfile
        from src.app.runtime import _pack_from_dict

        record["check"] = "torch-cuda" if args.pack in DRIVER_MIN else "torch" if args.pack == "torch-cpu" else "argos"
        record["unpacked_bytes"] = 0
        for item in files:
            path = work / "wheels" / item["name"]
            if not path.is_file():
                path = out_dir / item["name"]
            with zipfile.ZipFile(path) as archive:
                record["unpacked_bytes"] += sum(entry.file_size for entry in archive.infolist())
        record["revision"] = _pack_from_dict(record).revision
        catalog_path = ROOT / "locks" / "runtime-catalog.json"
        previous = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else []
        previous = [p for p in previous if (p["id"], p["os"]) != (record["id"], record["os"])]
        previous.append(record)
        previous.sort(key=lambda p: (p["os"], p["id"]))
        catalog_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_path = out_dir / f"{args.pack}-{args.os_tag}.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = update_summary(out_dir, record)

    lock_name = f"py310-{args.pack}-{args.os_tag}.lock"
    lock_dir = _resolve(args.lock_dir) if args.lock_dir else out_dir
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / lock_name
    lock_path.write_text(
        lock_text(args.pack, args.os_tag, python_tag, lock_pins), encoding="utf-8"
    )
    megabytes = record["size_bytes"] / 1e6
    print(
        f"{args.pack}/{args.os_tag}: файлов {len(files)}, {megabytes:.1f} МБ, "
        f"версия {top_version}"
    )
    print(f"Сводка: {record_path}")
    print(f"Сводка (общая): {summary}")
    print(f"Лок: {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
