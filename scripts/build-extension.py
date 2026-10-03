"""Сборка unpacked-расширения MV3 в dist/chromium и dist/firefox.

Без сети и без сборщиков: копирует extension/src, кладёт нужный манифест
и рисует PNG 16/48 через zlib. Pillow используется, только если уже стоит.
"""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = ROOT / "extension"
SRC_DIR = EXT_DIR / "src"
DIST_DIR = ROOT / "dist"

SOURCE_FILES = (
    "background.js",
    "content.js",
    "content.css",
    "popup.html",
    "popup.js",
    "options.html",
    "options.js",
)

ICON_OUTER = (20, 72, 120)
ICON_INNER = (244, 248, 252)


def png_bytes(size: int, outer: tuple[int, int, int], inner: tuple[int, int, int]) -> bytes:
    """Квадратный RGB PNG: рамка outer и светлая середина inner."""
    if size < 1:
        raise ValueError("size")
    margin = max(1, size // 8) if outer != inner else 0
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            edge = x < margin or y < margin or x >= size - margin or y >= size - margin
            rows.extend(outer if edge else inner)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def write_png(path: Path, size: int, outer: tuple[int, int, int], inner: tuple[int, int, int]) -> None:
    """Пишет иконку. Pillow — если импортируется, иначе тот же кадр через zlib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        path.write_bytes(png_bytes(size, outer, inner))
        return
    image = Image.new("RGB", (size, size), outer)
    margin = max(1, size // 8)
    if outer != inner:
        draw = ImageDraw.Draw(image)
        draw.rectangle((margin, margin, size - margin - 1, size - margin - 1), fill=inner)
    image.save(path, "PNG")


def _load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Некорректный манифест: {path}")
    return data


def _check_manifests(chromium: dict, firefox: dict) -> None:
    worker = chromium.get("background", {}).get("service_worker")
    if worker != "background.js":
        raise SystemExit("Манифест Chromium без service_worker background.js")
    scripts = firefox.get("background", {}).get("scripts")
    gecko = firefox.get("browser_specific_settings", {}).get("gecko", {}).get("id")
    if scripts != ["background.js"] or gecko != "image-localization-tool@local":
        raise SystemExit("Манифест Firefox без background.scripts или gecko id")


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _copy_sources(target: Path) -> None:
    for name in SOURCE_FILES:
        source = SRC_DIR / name
        if not source.is_file():
            raise SystemExit(f"Нет исходника расширения: {source}")
        shutil.copy2(source, target / name)


def _write_manifest(target: Path, manifest: dict) -> None:
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (target / "manifest.json").write_text(text, encoding="utf-8")


def _write_icons(*dirs: Path) -> None:
    for directory in dirs:
        write_png(directory / "icon16.png", 16, ICON_OUTER, ICON_INNER)
        write_png(directory / "icon48.png", 48, ICON_OUTER, ICON_INNER)


def build() -> None:
    """Собирает оба дерева dist и иконки в extension/icons."""
    chromium = _load_manifest(EXT_DIR / "manifest.chromium.json")
    firefox = _load_manifest(EXT_DIR / "manifest.firefox.json")
    _check_manifests(chromium, firefox)

    chromium_dir = DIST_DIR / "chromium"
    firefox_dir = DIST_DIR / "firefox"
    _reset_dir(chromium_dir)
    _reset_dir(firefox_dir)
    _copy_sources(chromium_dir)
    _copy_sources(firefox_dir)
    _write_manifest(chromium_dir, chromium)
    _write_manifest(firefox_dir, firefox)
    _write_icons(chromium_dir / "icons", firefox_dir / "icons", EXT_DIR / "icons")


def main() -> None:
    build()


if __name__ == "__main__":
    main()
