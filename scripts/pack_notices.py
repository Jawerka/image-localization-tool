"""Скопировать лицензионные тексты в каталог поставки."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE_FILES = (
    ("LICENSE", "LICENSE"),
    ("docs/LICENSE_INVENTORY.md", "LICENSE_INVENTORY.md"),
    ("docs/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
    ("docs/FONTS.md", "FONTS.md"),
    ("assets/README.md", "ARGOS_WHEEL.md"),
)


def copy_notices(destination: Path, root: Path = ROOT) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in NOTICE_FILES:
        source = root / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copyfile(source, destination / target_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    args = parser.parse_args()
    copy_notices(Path(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
