"""Собрать релизный манифест рантайма из сводки паков.

Читает ``dist/packs/packs.json`` (его пишет ``scripts/build-runtime-pack.py``),
подставляет URL ассетов релиза и пишет:

- ``dist/ilt-runtime-manifest-<ver>.json`` — ассет релиза;
- ``src/app/runtime_manifest.json`` — встроенную копию (по умолчанию):
  базовая сборка несёт реальные sha256, и установка работает офлайн.

Запуск:
    python scripts/build-runtime-manifest.py
    python scripts/build-runtime-manifest.py --no-bundled
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.smoke_dist import read_app_version  # noqa: E402
from src.app.runtime import RELEASE_BASE  # noqa: E402

KIND_ORDER = {"torch": 0, "argos": 1}


def build_manifest(version: str, packs: list[dict], url_base: str = RELEASE_BASE) -> dict:
    """Записи packs.json → манифест с URL релиза."""
    entries: list[dict] = []
    for record in packs:
        filename = str(record.get("file") or "")
        if not filename:
            continue
        entry = {
            "id": str(record.get("id") or ""),
            "title": str(record.get("title") or record.get("id") or ""),
            "kind": str(record.get("kind") or ""),
            "os": str(record.get("os") or ""),
            "arch": str(record.get("arch") or "x64"),
            "python": str(record.get("python") or ""),
            "version": str(record.get("version") or ""),
            "url": f"{url_base}/v{version}/{filename}",
            "sha256": str(record.get("sha256") or ""),
            "size_bytes": int(record.get("size_bytes") or 0),
        }
        if record.get("driver_min") is not None:
            entry["driver_min"] = int(record["driver_min"])
        entries.append(entry)
    entries.sort(key=lambda item: (item["os"], KIND_ORDER.get(item["kind"], 9), item["id"]))
    return {"schema": 1, "app": version, "packs": entries}


def merge_entries(base: list[dict], overlay: list[dict]) -> list[dict]:
    """Слить записи манифеста по (id, os): новые перекрывают старые."""
    merged: list[dict] = []
    for entry in overlay:
        merged.append(entry)
    keys = {(item.get("id"), item.get("os")) for item in overlay}
    for entry in base:
        if (entry.get("id"), entry.get("os")) not in keys:
            merged.append(entry)
    merged.sort(
        key=lambda item: (
            str(item.get("os")),
            KIND_ORDER.get(str(item.get("kind")), 9),
            str(item.get("id")),
        )
    )
    return merged


def load_packs(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Ожидался список записей: {path}")
    return [item for item in data if isinstance(item, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Манифест рантайма релиза")
    parser.add_argument("--packs", default="dist/packs/packs.json")
    parser.add_argument("--out", default="", help="по умолчанию dist/ilt-runtime-manifest-<ver>.json")
    parser.add_argument("--bundled", default="src/app/runtime_manifest.json")
    parser.add_argument("--no-bundled", action="store_true", help="не трогать встроенную копию")
    parser.add_argument("--url-base", default=RELEASE_BASE)
    args = parser.parse_args(argv)

    version = read_app_version(ROOT)
    packs_path = Path(args.packs)
    if not packs_path.is_absolute():
        packs_path = ROOT / packs_path
    manifest = build_manifest(version, load_packs(packs_path), args.url_base)

    out_path = Path(args.out) if args.out else Path("dist") / f"ilt-runtime-manifest-{version}.json"
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"Манифест релиза: {out_path} (паков: {len(manifest['packs'])})")

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
                manifest["packs"] = merge_entries(old_packs, manifest["packs"])
        bundled.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Встроенная копия: {bundled} (паков: {len(manifest['packs'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
