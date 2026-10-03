#!/usr/bin/env python3
"""Скачать детектор, LaMa-manga и шрифт Heroika, при необходимости поставить torch+CUDA.

Проверяет LLM-сервер через /v1/models.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
FONTS = ROOT / "src" / "resources" / "fonts"

LAMA_URL = (
    "https://github.com/Sanster/models/releases/download/"
    "AnimeMangaInpainting/anime-manga-big-lama.pt"
)
FONT_URL = (
    "https://github.com/ChewKeanHo/visuals-fonts-heroika-namikus/releases/download/"
    "v1.0.0/Heroika.Namikus.-Regular.otf"
)
OFL_URL = "https://raw.githubusercontent.com/ChewKeanHo/visuals-fonts-heroika-namikus/main/LICENSE"
DETECTOR_INT8_URL = (
    "https://huggingface.co/ogkalu/comic-text-and-bubble-detector/resolve/main/"
    "detector-v4-s_int8.onnx"
)
DEFAULT_LLM = "http://127.0.0.1:8080/v1"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  есть: {dest.relative_to(ROOT)}")
        return
    print(f"  скачиваю {dest.name} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  готово: {dest.stat().st_size // (1024 * 1024)} МБ")


def install_torch_cuda() -> None:
    print("Ставлю torch и torchvision с CUDA (cu130)...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "torch==2.11.0", "torchvision==0.26.0",
            "--index-url", "https://download.pytorch.org/whl/cu130",
        ],
        check=True,
    )


def check_llm(base_url: str) -> None:
    import json
    url = base_url.rstrip("/") + "/models"
    print(f"Проверка LLM: {url}")
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"  сервер недоступен: {exc}")
        return
    names = [item.get("id") for item in payload.get("data") or [] if item.get("id")]
    if not names:
        print("  ответ без моделей")
        return
    print("  модели:")
    for name in names:
        print(f"    - {name}")


def ensure_detector() -> None:
    """Скачать int8-детектор, если нет ни fp32, ни int8."""
    preferred = MODELS / "ogkalu-detector.onnx"
    int8 = MODELS / "ogkalu-detector-v4-s_int8.onnx"
    if preferred.exists() and preferred.stat().st_size > 0:
        print(f"  есть: {preferred.relative_to(ROOT)}")
        return
    if int8.exists() and int8.stat().st_size > 0:
        print(f"  есть: {int8.relative_to(ROOT)}")
        return
    download(DETECTOR_INT8_URL, int8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Модели и шрифт для пайплайна v2")
    parser.add_argument("--torch-cuda", action="store_true", help="Поставить torch с CUDA")
    parser.add_argument("--llm-url", default=DEFAULT_LLM, help="Базовый URL /v1")
    args = parser.parse_args()

    print("Модели:")
    ensure_detector()
    download(LAMA_URL, MODELS / "anime-manga-big-lama.pt")

    print("Шрифт:")
    download(FONT_URL, FONTS / "Heroika-Regular.otf")
    try:
        download(OFL_URL, FONTS / "OFL.txt")
    except Exception as exc:
        print(f"  OFL не скачался ({exc}), пишу короткую пометку")
        notice = FONTS / "OFL.txt"
        if not notice.exists():
            notice.write_text(
                "Heroika (Namikus) by Namik Mardakhaev.\n"
                "Licensed under the SIL Open Font License 1.1: https://scripts.sil.org/OFL\n",
                encoding="utf-8",
            )

    if args.torch_cuda:
        install_torch_cuda()

    check_llm(args.llm_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
