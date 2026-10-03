"""Проверка и докачка моделей без тяжёлого запроса к LLM.

Адреса LaMa и шрифта совпадают с ``scripts/setup_models.py``.
У детектора fp32 отдельного URL нет, качается только int8.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from src.utils.paths import resolve_font, resolve_model

# Совпадает с scripts/setup_models.py (LAMA_URL, FONT_URL).
LAMA_URL = (
    "https://github.com/Sanster/models/releases/download/"
    "AnimeMangaInpainting/anime-manga-big-lama.pt"
)
FONT_URL = (
    "https://github.com/ChewKeanHo/visuals-fonts-heroika-namikus/releases/download/"
    "v1.0.0/Heroika.Namikus.-Regular.otf"
)
DETECTOR_INT8_URL = (
    "https://huggingface.co/ogkalu/comic-text-and-bubble-detector/resolve/main/"
    "detector-v4-s_int8.onnx"
)

LAMA_FILENAME = "anime-manga-big-lama.pt"
FONT_FILENAME = "Heroika-Regular.otf"
DETECTOR_NAMES = ("ogkalu-detector.onnx", "ogkalu-detector-v4-s_int8.onnx")
DETECTOR_INT8_FILENAME = "ogkalu-detector-v4-s_int8.onnx"

_DOWNLOADS = {
    "lama": (LAMA_URL, LAMA_FILENAME),
    "font": (FONT_URL, FONT_FILENAME),
    "detector": (DETECTOR_INT8_URL, DETECTOR_INT8_FILENAME),
}

# Статические OFL TTF из google/fonts (не variable).
# PT Sans — диалог, Russo One — крик, Marck Script — рукопись: в них есть кириллица.
# Creepster — слот sfx; кириллицы в файле может не быть.
FONT_PACK = (
    (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PT_Sans-Web-Regular.ttf",
        "PT_Sans-Web-Regular.ttf",
    ),
    (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/russoone/RussoOne-Regular.ttf",
        "RussoOne-Regular.ttf",
    ),
    (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/marckscript/MarckScript-Regular.ttf",
        "MarckScript-Regular.ttf",
    ),
    (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/creepster/Creepster-Regular.ttf",
        "Creepster-Regular.ttf",
    ),
)


def status(models_override: str = "") -> dict:
    """Какие файлы уже лежат на диске. Сеть не используется."""
    override = models_override.strip() if models_override else None
    return {
        "detector": _model_entry(DETECTOR_NAMES, override),
        "lama": _model_entry((LAMA_FILENAME,), override),
        "font": _font_entry(),
    }


def download(kind: str, dest_dir: str | Path, progress=None) -> Path:
    """Скачать модель или шрифт в ``dest_dir``.

    Если файл уже есть и его размер больше нуля, запрос не выполняется.
    ``progress(done_bytes, total_bytes | None)`` вызывается по ходу чтения.
    ``kind="font_pack"`` отдаёт набор OFL в ``download_font_pack``
    (у этого колбэка другая сигнатура).
    """
    if kind == "font_pack":
        return download_font_pack(dest_dir, progress)
    spec = _DOWNLOADS.get(kind)
    if spec is None:
        raise ValueError(f"Неизвестный файл для скачивания: {kind}")
    url, filename = spec
    directory = Path(dest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / filename
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    request = urllib.request.Request(url)
    temporary = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header else None
            done = 0
            if progress is not None:
                progress(0, total)
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        temporary.replace(dest)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return dest


def download_font_pack(dest_dir: str | Path, progress=None) -> Path:
    """Скачать небольшой набор OFL-шрифтов в ``dest_dir``.

    Уже существующие непустые файлы пропускаются.
    ``progress(filename, index, total)`` вызывается перед каждым файлом,
    ``index`` считается с 1. При ошибке сети недокачанный ``.part`` удаляется
    и исключение пробрасывается дальше.
    """
    directory = Path(dest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    total = len(FONT_PACK)
    for index, (url, filename) in enumerate(FONT_PACK, start=1):
        if progress is not None:
            progress(filename, index, total)
        dest = directory / filename
        if dest.is_file() and dest.stat().st_size > 0:
            continue
        request = urllib.request.Request(url)
        temporary = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            temporary.replace(dest)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
    return directory


def check_llm(base_url: str, api_key: str = "") -> dict:
    """GET ``{base}/models`` с таймаутом 10 с. Картинки здесь не проверяются."""
    base = str(base_url or "").strip()
    if not base:
        return {"ok": False, "reason": "empty", "models": []}
    url = base.rstrip("/") + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "models": []}
    models: list[str] = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("id"):
            models.append(str(item["id"]))
        elif isinstance(item, str) and item:
            models.append(item)
    return {"ok": True, "models": models}


def _model_entry(names: tuple[str, ...], override: str | None) -> dict:
    fallback = ""
    for name in names:
        path = resolve_model(name, override)
        fallback = str(path)
        if path.is_file() and path.stat().st_size > 0:
            return {"present": True, "path": str(path)}
    return {"present": False, "path": fallback}


def _font_entry() -> dict:
    path = resolve_font(FONT_FILENAME)
    present = path.is_file() and path.stat().st_size > 0
    return {"present": present, "path": str(path)}
