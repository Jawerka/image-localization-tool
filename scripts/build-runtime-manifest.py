"""Собрать релизный манифест рантайма (schema 2) из сводки локов.

Читает сводки ``dist/locks/packs.json`` (пишет ``scripts/build_runtime_locks.py``),
переносит wheels-записи как есть и пишет:

- ``dist/ilt-runtime-manifest-<ver>.json`` — ассет релиза (проверяется
  ``validate_manifest`` до записи);
- ``src/app/runtime_manifest.json`` — встроенную копию (по умолчанию), сливая
  со старыми записями: базовая сборка работает офлайн.

Запуск:
    python scripts/build-runtime-manifest.py
    python scripts/build-runtime-manifest.py --no-bundled
    python scripts/build-runtime-manifest.py --packs a.json --packs b.json --no-bundled
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manifest_tools import build_manifest, merge_entries, validate_manifest  # noqa: E402
from scripts.smoke_dist import read_app_version  # noqa: E402
from src.app.runtime import RELEASE_BASE  # noqa: E402


def load_packs(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise SystemExit(f"Ожидался список записей: {path}")
    return [item for item in data if isinstance(item, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Манифест рантайма релиза (schema 2)")
    parser.add_argument(
        "--packs",
        action="append",
        default=None,
        help="сводка локов; можно указать несколько (поздние перекрывают ранние)",
    )
    parser.add_argument("--out", default="", help="по умолчанию dist/ilt-runtime-manifest-<ver>.json")
    parser.add_argument("--bundled", default="src/app/runtime_manifest.json")
    parser.add_argument("--no-bundled", action="store_true", help="не трогать встроенную копию")
    parser.add_argument("--url-base", default=RELEASE_BASE)
    args = parser.parse_args(argv)

    version = read_app_version(ROOT)
    entries: list[dict] = []
    for packs_arg in args.packs or ["dist/locks/packs.json"]:
        packs_path = Path(packs_arg)
        if not packs_path.is_absolute():
            packs_path = ROOT / packs_path
        if not packs_path.is_file():
            raise SystemExit(f"Нет сводки локов: {packs_path}. Сначала build_runtime_locks.py.")
        entries = merge_entries(entries, load_packs(packs_path))
    manifest = build_manifest(version, entries, args.url_base)

    issues = validate_manifest(manifest)
    if issues:
        for issue in issues:
            print(f"ОШИБКА: {issue}", file=sys.stderr)
        raise SystemExit("Манифест не прошёл валидацию полноты")

    out_path = Path(args.out) if args.out else Path("dist") / f"ilt-runtime-manifest-{version}.json"
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"Манифест релиза: {out_path} (schema 2, паков: {len(manifest['packs'])})")

    if not args.no_bundled:
        bundled = Path(args.bundled)
        if not bundled.is_absolute():
            bundled = ROOT / bundled
        if bundled.is_file():
            try:
                existing = json.loads(bundled.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing = {}
            old_packs = existing.get("packs") if isinstance(existing, dict) else None
            if isinstance(old_packs, list):
                # Старые записи (в т.ч. плейсхолдеры schema 1) остаются запасным
                # путём; встроенную копию не валидируем строго.
                manifest["packs"] = merge_entries(old_packs, manifest["packs"])
        bundled.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Встроенная копия: {bundled} (паков: {len(manifest['packs'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
