"""Локальная приёмка использует фиксированный каталог, не разрешает зависимости."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.manifest_tools import build_manifest
from scripts.smoke_dist import read_app_version
from src.app import downloads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", default="torch-cpu,argos")
    parser.add_argument("--release", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    destination = Path(args.release)
    destination.mkdir(parents=True, exist_ok=True)
    entries = json.loads((ROOT / "locks/runtime-catalog.json").read_text(encoding="utf-8"))
    entries = [p for p in entries if p["os"] == "win" and p["id"] in args.packs.split(",")]
    for pack in entries:
        for record in pack["files"]:
            item = downloads.Artifact(record["name"], (record["url"],), record["sha256"], record["size_bytes"])
            target = destination / item.name
            if not downloads.valid(target, item):
                cached = list((ROOT / "dist/locks/stage").rglob(item.name))
                cached += list((ROOT / "assets").glob(item.name))
                source = next((p for p in cached if downloads.valid(p, item)), None)
                if source is None:
                    source = downloads.fetch(item)
                target.unlink(missing_ok=True)
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copyfile(source, target)
            record["url"] = target.resolve().as_uri()
            record.pop("mirrors", None)
    manifest = build_manifest(read_app_version(ROOT), entries, destination.resolve().as_uri())
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Fixed local catalog:", len(entries), "packs")


if __name__ == "__main__":
    main()
