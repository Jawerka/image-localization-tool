"""Сборка расширения без браузера: манифесты Chromium и Firefox."""

from __future__ import annotations

import importlib.util
import io
import json
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-extension.py"
CHROMIUM = ROOT / "dist" / "chromium" / "manifest.json"
FIREFOX = ROOT / "dist" / "firefox" / "manifest.json"

ERROR_STRINGS = ("сервер не найден", "ключ отозван", "очередь заполнена")


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    assert data[12:16] == b"IHDR", path
    return struct.unpack(">II", data[16:24])


def _load_build():
    spec = importlib.util.spec_from_file_location("build_extension", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_png_bytes_is_square():
    raw = _load_build().png_bytes(220, (30, 90, 160), (30, 90, 160))
    image = Image.open(io.BytesIO(raw))
    assert image.size == (220, 220)
    assert image.getpixel((0, 0)) == (30, 90, 160)


def test_extension_build_manifests():
    subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)

    chromium = json.loads(CHROMIUM.read_text(encoding="utf-8"))
    firefox = json.loads(FIREFOX.read_text(encoding="utf-8"))

    assert chromium["name"] == "Image Localization Tool"
    assert chromium["background"]["service_worker"] == "background.js"
    assert chromium["background"]["type"] == "module"
    assert "service_worker" not in firefox["background"]
    assert firefox["background"]["scripts"] == ["background.js"]
    assert firefox["browser_specific_settings"]["gecko"]["id"] == "image-localization-tool@local"

    for tree in (ROOT / "dist" / "chromium", ROOT / "dist" / "firefox"):
        assert (tree / "background.js").read_bytes() == (ROOT / "extension" / "src" / "background.js").read_bytes()
        assert _png_size(tree / "icons" / "icon16.png") == (16, 16)
        assert _png_size(tree / "icons" / "icon48.png") == (48, 48)

    assert _png_size(ROOT / "extension" / "icons" / "icon16.png") == (16, 16)
    assert _png_size(ROOT / "extension" / "icons" / "icon48.png") == (48, 48)

    background = (ROOT / "extension" / "src" / "background.js").read_text(encoding="utf-8")
    assert "ilt-translate-image" in background
    assert "Перевести изображение" in background
    options = (ROOT / "extension" / "src" / "options.js").read_text(encoding="utf-8")
    for text in ERROR_STRINGS:
        assert text in options
        assert text in background
