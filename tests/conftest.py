"""Общие фикстуры для тестов."""

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TEST_IMG_DIR = ROOT / "test-img"


@pytest.fixture
def white_image():
    """Простое белое изображение 400x200."""
    return Image.new("RGB", (400, 200), "white")


@pytest.fixture
def test_img_pairs():
    """Пары (изображение, идеальная маска) из локальной папки test-img."""
    if not TEST_IMG_DIR.is_dir():
        return []
    pairs = []
    for stem in ("test-1", "test-2", "test-3", "test-4", "test-5"):
        for ext in (".jpg", ".png"):
            img = TEST_IMG_DIR / f"{stem}{ext}"
            if not img.exists():
                continue
            for mask_ext in (".jpg", ".png"):
                mask = TEST_IMG_DIR / f"{stem}-mask{mask_ext}"
                if mask.exists():
                    pairs.append((img, mask))
                    break
            break
    return pairs
