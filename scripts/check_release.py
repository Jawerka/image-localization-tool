"""Гейт релиза рантайма: Tier 1 (структура + HEAD) и Tier 2 (установка + import).

Tier 1 — без скачивания тел: ``validate_manifest`` (сумма ``size_bytes``,
64-hex sha256, размеры > 0) и HEAD каждого URL манифеста (PyPI CDN, PyTorch
CDN, ассеты релиза) с контролем ``Content-Length`` против ``size_bytes``.

Tier 2 (``--deep``) — глубокий прогон: установка ``torch-cpu`` из манифеста во
временный ``ILT_INSTALL_ROOT`` через ``src.app.runtime`` и ``import torch`` в
subprocess. Результат кэшируется в ``deep.json`` по sha256 входных артефактов
(setup/portable/server/manifest), чтобы повторный прогон не переигрывался.

Запуск:
    python scripts/check_release.py --manifest dist/ilt-runtime-manifest-1.0.1.json
    python scripts/check_release.py --manifest … --assets dist --deep
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manifest_tools import validate_manifest  # noqa: E402
from scripts.smoke_dist import read_app_version  # noqa: E402

CACHE_SCHEMA = 1
_ANONYMOUS = False
_ASSET_PATTERNS = ("*setup.exe", "*portable.zip", "*server-*.zip", "*server-*.tar.gz")


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _github_token() -> str:
    if _ANONYMOUS:
        return ""
    return (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def github_asset_check(url: str, token: str, timeout: float) -> tuple[bool, str, int | None] | None:
    """Ассет релиза GitHub через API: draft-ассеты анонимно недоступны (404).

    ``None`` — URL не наш релиз или токена нет: вызывающий делает обычный HEAD.
    """
    if not token:
        return None
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").casefold() not in ("github.com", "www.github.com"):
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 6 or segments[2] != "releases" or segments[3] != "download":
        return None
    owner, repo, tag, name = segments[0], segments[1], segments[4], "/".join(segments[5:])
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    request = urllib.request.Request(
        api,
        headers={
            "User-Agent": f"ImageLocalizationTool/{read_app_version(ROOT)}",
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"GitHub API HTTP {exc.code}", None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or exc.__class__.__name__, None
    for asset in payload.get("assets") or []:
        if asset.get("name") == name:
            size = int(asset.get("size") or 0)
            return True, "ассет релиза (API)", size if size > 0 else None
    return False, f"ассет {name} не найден в релизе {tag}", None


def head_check(url: str, timeout: float) -> tuple[bool, str, int | None]:
    """HEAD запроса; возвращает (ок, описание, Content-Length|None)."""
    api_result = github_asset_check(url, _github_token(), timeout)
    if api_result is not None:
        return api_result
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": f"ImageLocalizationTool/{read_app_version(ROOT)}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            headers = getattr(response, "headers", None)
            raw = headers.get("Content-Length") if headers is not None else None
            length = int(raw) if raw and str(raw).isdigit() else None
            return status == 200, f"HTTP {status}", length
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}", None
    except Exception as exc:  # noqa: BLE001 — любая сетевая ошибка = проблема URL
        return False, str(exc) or exc.__class__.__name__, None


def _url_jobs(manifest: dict) -> list[tuple[str, int, str]]:
    jobs: list[tuple[str, int, str]] = []
    for record in manifest.get("packs") or []:
        if not isinstance(record, dict):
            continue
        label = f"{record.get('id')}/{record.get('os')}"
        files = record.get("files")
        if isinstance(files, list) and files:
            for item in files:
                if isinstance(item, dict) and item.get("url"):
                    jobs.append(
                        (str(item["url"]), int(item.get("size_bytes") or 0), f"{label} {item.get('name') or '?'}")
                    )
        elif record.get("url"):
            jobs.append((str(record["url"]), int(record.get("size_bytes") or 0), f"{label} archive"))
    return jobs


def check_urls(manifest: dict, timeout: float, workers: int = 8) -> tuple[list[str], list[str]]:
    """HEAD всех URL; возвращает (ошибки, предупреждения)."""
    failures: list[str] = []
    warnings: list[str] = []
    jobs = _url_jobs(manifest)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(head_check, url, timeout): (label, size)
            for url, size, label in jobs
        }
        for future in as_completed(futures):
            label, size = futures[future]
            ok, detail, length = future.result()
            if not ok:
                failures.append(f"{label}: {detail}")
            elif length is None:
                warnings.append(f"{label}: нет Content-Length — размер не сверен")
            elif size and length != size:
                failures.append(f"{label}: Content-Length {length} ≠ size_bytes {size}")
    return failures, warnings


def cache_key(assets_dir: Path, manifest_path: Path) -> str:
    """Ключ кэша: sha256 по хэшам доступных артефактов и манифеста."""
    paths: set[Path] = set()
    for pattern in _ASSET_PATTERNS:
        paths.update(path for path in assets_dir.glob(pattern) if path.is_file())
    if manifest_path.is_file():
        paths.add(manifest_path)
    if not paths:
        return "empty"
    parts = [f"{path.name}:{_file_sha256(path)}" for path in sorted(paths, key=lambda p: p.name)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def deep_install(manifest_path: Path, pack_id: str, timeout: float) -> tuple[bool, str]:
    """Установить пак из манифеста во временный корень и импортировать torch."""
    with tempfile.TemporaryDirectory(prefix="ilt-deep-") as tmp:
        env = dict(os.environ)
        env["ILT_INSTALL_ROOT"] = tmp
        env["ILT_RUNTIME_MANIFEST_URL"] = manifest_path.as_uri()
        script = (
            "import sys\n"
            "from src.app import runtime\n"
            f"dest = runtime.download_and_install({pack_id!r})\n"
            "sys.path.insert(0, str(dest / 'site-packages'))\n"
            "import torch\n"
            "print('import torch ok:', torch.__version__)\n"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"таймаут {int(timeout)} с"
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-4:]
            return False, " | ".join(line.strip() for line in tail) or "код != 0"
        lines = (result.stdout or "").strip().splitlines()
        return True, lines[-1].strip() if lines else "ok"


def load_cache(path: Path) -> dict:
    if not path.is_file():
        return {"schema": CACHE_SCHEMA, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"schema": CACHE_SCHEMA, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"schema": CACHE_SCHEMA, "entries": {}}
    return data


def main(argv: list[str] | None = None) -> int:
    global _ANONYMOUS
    version = read_app_version(ROOT)
    parser = argparse.ArgumentParser(description="Гейт релиза рантайма (Tier 1 + Tier 2)")
    parser.add_argument(
        "--manifest",
        default=f"dist/ilt-runtime-manifest-{version}.json",
        help="релизный манифест schema 2",
    )
    parser.add_argument("--assets", default="dist", help="каталог артефактов для ключа кэша")
    parser.add_argument("--deep", action="store_true", help="выполнить Tier 2 (установка + import)")
    parser.add_argument("--refresh-deep", action="store_true", help="игнорировать кэш Tier 2")
    parser.add_argument("--cache", default="build/deep.json")
    parser.add_argument("--pack", default="torch-cpu", help="пак для Tier 2")
    parser.add_argument("--skip-remote", action="store_true", help="без HEAD-проверок")
    parser.add_argument("--anonymous", action="store_true", help="проверять доступность без токена разработчика")
    parser.add_argument("--components", default="", help="также проверить каталог моделей/OCR/языков/шрифтов")
    parser.add_argument("--timeout", type=float, default=30.0, help="таймаут HEAD, с")
    args = parser.parse_args(argv)
    _ANONYMOUS = args.anonymous

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.is_file():
        print(f"Нет манифеста: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    failures: list[str] = []
    issues = validate_manifest(manifest)
    if issues:
        failures.extend(issues)
    else:
        packs = len(manifest.get("packs") or [])
        print(f"Tier 1 (структура): ок, паков {packs}")

    if failures:
        for issue in failures:
            print(f"ОШИБКА: {issue}", file=sys.stderr)
        return 1

    if not args.skip_remote:
        if args.components:
            from src.app.component_catalog import load

            resources_path = Path(args.components)
            resources = load(resources_path if resources_path.is_absolute() else ROOT / resources_path)
            records = [{"id": c.id, "os": "all", "files": [{"name": f.name, "url": f.urls[0],
                       "size_bytes": f.size_bytes} for f in c.files]} for c in resources]
            manifest = {**manifest, "packs": [*manifest["packs"], *records]}
        url_failures, warnings = check_urls(manifest, args.timeout)
        for line in warnings:
            print(f"ПРЕДУПРЕЖДЕНИЕ: {line}")
        failures.extend(url_failures)
        if url_failures:
            for issue in url_failures:
                print(f"ОШИБКА: {issue}", file=sys.stderr)
            return 1
        print(f"Tier 1 (HEAD): ок, URL {len(_url_jobs(manifest))}")

    if args.deep:
        assets_dir = Path(args.assets)
        if not assets_dir.is_absolute():
            assets_dir = ROOT / assets_dir
        cache_path = Path(args.cache)
        if not cache_path.is_absolute():
            cache_path = ROOT / cache_path
        key = cache_key(assets_dir, manifest_path)
        cache = load_cache(cache_path)
        entry = cache["entries"].get(key)
        if entry and entry.get("ok") and not args.refresh_deep:
            print(f"Tier 2: кэш deep.json ({entry.get('detail') or 'ok'})")
        else:
            print(f"Tier 2: установка {args.pack} + import torch…")
            ok, detail = deep_install(manifest_path, args.pack, timeout=max(args.timeout, 3600.0))
            cache["entries"][key] = {"checked_at": time.time(), "ok": ok, "detail": detail}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if not ok:
                print(f"ОШИБКА Tier 2: {detail}", file=sys.stderr)
                return 1
            print(f"Tier 2: ок ({detail})")

    print("Гейт пройден.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
