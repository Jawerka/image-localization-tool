"""Проверка и докачка моделей без тяжёлого запроса к LLM.

Адреса LaMa и шрифта совпадают с ``scripts/setup_models.py``.
У детектора fp32 отдельного URL нет, качается только int8.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from src.utils.paths import components_root, install_root, models_dir, resolve_font, resolve_model

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


def dest_dir(kind: str, models_override: str | Path | None = None) -> Path:
    """Куда класть файл: шрифт в ``fonts`` рядом с программой, остальное в модели."""
    if kind == "font":
        return components_root() / "fonts"
    override = str(models_override).strip() if models_override else ""
    return models_dir(override or None)


def status(models_override: str = "") -> dict:
    """Какие файлы уже лежат на диске. Сеть не используется."""
    override = models_override.strip() if models_override else None
    return {
        "detector": _model_entry(DETECTOR_NAMES, override),
        "lama": _model_entry((LAMA_FILENAME,), override),
        "font": _font_entry(),
    }


def download(kind: str, dest_dir: str | Path, progress=None, pause=None) -> Path:
    """Скачать проверенный ресурс общим загрузчиком, сохраняя прогресс при сбое."""
    from src.app import component_catalog

    if kind == "font_pack":
        return download_font_pack(dest_dir, progress, pause)
    try:
        component = component_catalog.by_id(kind)
    except StopIteration as exc:
        raise ValueError("Неизвестный файл для скачивания") from exc
    folder = component_catalog.install(component, pause=pause, models_override=str(dest_dir),
        progress=lambda done, total, state, message: progress(done, total) if progress else None)
    result = folder / component.files[0].name
    from src.utils.paths import components_root

    destination = Path(dest_dir)
    default = components_root() / ("fonts" if kind == "font" else "models")
    if destination != default:
        from src.app import downloads
        import shutil

        destination.mkdir(parents=True, exist_ok=True)
        target = destination / result.name
        if not downloads.valid(target, component.files[0]):
            downloads.ensure_space(destination, result.stat().st_size)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(result, temporary)
            temporary.replace(target)
        result = target
    return result


def download_font_pack(dest_dir: str | Path, progress=None, pause=None) -> Path:
    """Дополнительные шрифты устанавливаются одной проверенной ревизией."""
    from src.app import component_catalog

    component = component_catalog.by_id("font-pack")
    return component_catalog.install(component, pause=pause,
        progress=lambda done, total, state, message: progress(component.title, 1, 1) if progress else None)


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


def verify_llm(base_url: str, api_key: str, model: str = "") -> dict:
    """Пробный ``chat/completions`` с ключом: проверяет, что сервер его принимает.

    Публичный ``/models`` (OpenRouter) ничего не доказывает про ключ, поэтому
    после успешной проверки списка моделей шлём минимальный запрос. 401/403 —
    ключ отклонён, прочие ошибки — как есть.
    """
    base = str(base_url or "").strip()
    key = str(api_key or "").strip()
    if not base or not key:
        return {"ok": True, "reason": ""}
    body = json.dumps({
        "model": str(model or "").strip(),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "reason": f"Ключ API отклонён (HTTP {exc.code})"}
        return {"ok": False, "reason": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True, "reason": ""}


def _model_entry(names: tuple[str, ...], override: str | None) -> dict:
    fallback = ""
    for name in names:
        path = resolve_model(name, override)
        fallback = str(path)
        if _checked_file(path):
            return {"present": True, "path": str(path)}
    return {"present": False, "path": fallback}


def _font_entry() -> dict:
    path = resolve_font(FONT_FILENAME)
    present = _checked_file(path)
    return {"present": present, "path": str(path)}


def _checked_file(path: Path) -> bool:
    """Официальный файл сверяется с каталогом, произвольная fp32-модель остаётся совместимой."""
    from src.app import component_catalog, downloads

    if not path.is_file() or path.stat().st_size == 0:
        return False
    for component in component_catalog.load():
        for artifact in component.files:
            if artifact.name == path.name:
                if component_catalog.installed_file(path.name) == path:
                    return True
                return downloads.valid(path, artifact)
    return True
