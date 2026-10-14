"""Проверка компонентов в чистом процессе до их активации."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from src.app import downloads


@lru_cache(maxsize=1)
def validation_identity() -> str:
    """Обновлённая frozen-база повторно проверяет уже скачанные компоненты."""
    from src.app import __version__

    return downloads.digest(Path(sys.executable)) if getattr(sys, "frozen", False) else f"dev-{__version__}-{sys.version_info.major}{sys.version_info.minor}"


def probe(spec: dict, timeout: int = 180) -> dict:
    """Frozen-проверка использует тот же executable, а не Python из PATH."""
    with tempfile.TemporaryDirectory(prefix="ilt-check-") as folder:
        path = Path(folder) / "check.json"
        downloads.atomic_json(path, spec)
        command = ([sys.executable, "--component-check", str(path)] if getattr(sys, "frozen", False)
                   else [sys.executable, "-m", "src.app.component_check", str(path)])
        result = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[2]) if not getattr(sys, "frozen", False) else None,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            try:
                detail = json.loads((Path(folder) / "check.result.json").read_text(encoding="utf-8"))["error"]
            except (OSError, ValueError, KeyError):
                detail = (result.stderr or result.stdout)[-1500:]
            raise RuntimeError("Компонент не прошёл проверку совместимости: " + detail)
        try:
            return json.loads((Path(folder) / "check.result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("Проверка компонента не вернула результат") from exc


def run(path: str) -> int:
    """Результат передаётся файлом: в оконной сборке stdout направлен в лог."""
    source = Path(path)
    try:
        spec = json.loads(source.read_text(encoding="utf-8"))
        os.environ["ARGOS_CHUNK_TYPE"] = "MINISBD"
        from src.app import runtime

        runtime._attach_stdlib()
        if spec.get("site"):
            runtime.activate_path(Path(spec["site"]).parent)
        else:
            runtime.startup()
        result = check(spec)
        downloads.atomic_json(source.with_name("check.result.json"), result)
        return 0
    except Exception as exc:
        downloads.atomic_json(source.with_name("check.result.json"), {"ok": False, "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 1


def check(spec: dict) -> dict:
    kind = spec["kind"]
    if kind == "prepare-offline":
        from src.app.preparation import Manager
        import time

        manager = Manager()
        manager.start({"translator_backend": "argos", "source_lang": "en", "target_lang": "ru", "device": spec["device"]})
        while manager.busy():
            time.sleep(0.2)
        if manager.current()["state"] != "ready":
            raise RuntimeError(manager.current().get("error") or "Подготовка не завершена")
        return {"ok": True}
    if kind == "offline-functional":
        # Скрытые загрузки библиотек считаются ошибкой приёмки.
        import urllib.request
        import requests

        attempts = []
        def no_network(*args, **kwargs):
            attempts.append(True)
            raise RuntimeError("Обработка подготовленного приложения попыталась обратиться к сети")
        urllib.request.urlopen = no_network
        requests.sessions.Session.request = no_network
        from PIL import Image, ImageDraw, ImageFont
        from src.config import Config
        from src.page_pipeline import PagePipeline
        from src.utils.paths import resolve_font
        from src.components.translator import TranslatorService

        translator = TranslatorService()
        translated = translator.translate_texts(["Hello."], "en", "ru")
        if translator.last_error or not translated or not translated[0].strip():
            raise RuntimeError(translator.last_error or "Оффлайн-перевод не работает")
        image = Image.new("RGB", (640, 400), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((40, 40, 600, 360), outline="black", width=4)
        draw.text((220, 165), "HELLO", fill="black", font=ImageFont.truetype(str(resolve_font("Heroika-Regular.otf")), 42))
        path = Path(spec["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        config = Config(ocr_backend="rapid", translator_backend="argos", llm_base_url="", device=spec.get("device", "cpu"))
        result = PagePipeline(config).process(path, source_lang="en", target_lang="ru")
        if attempts:
            raise RuntimeError("Пайплайн предпринял скрытую попытку загрузки")
        result.image.save(path.with_name("offline-result.png"))
        return {"ok": True, "regions": len(result.regions), "warnings": result.warnings}
    if kind in ("torch", "torch-cuda"):
        import torch

        value = torch.tensor([1., 2.]) + 1
        assert value.sum().item() == 5
        cuda = False
        if kind == "torch-cuda":
            value = torch.tensor([1., 2.], device="cuda") + 1
            assert value.sum().item() == 5
            torch.cuda.synchronize()
            cuda = True
        return {"ok": True, "cuda": cuda}
    if kind == "argos":
        import argostranslate.package
        import argostranslate.translate

        return {"ok": True}
    if kind == "onnx":
        import onnxruntime

        session = onnxruntime.InferenceSession(spec["path"], providers=["CPUExecutionProvider"])
        assert session.get_inputs()
    elif kind == "lama":
        import torch

        torch.jit.load(spec["path"], map_location="cpu")
    elif kind == "font":
        from PIL import ImageFont

        ImageFont.truetype(spec["path"], 16)
    elif kind == "rapidocr":
        import numpy as np
        from rapidocr import RapidOCR

        engine = RapidOCR(params=spec["params"])
        engine(np.full((64, 128, 3), 255, dtype=np.uint8))
    elif kind == "argos-language":
        os.environ["ARGOS_PACKAGES_DIR"] = spec["path"]
        os.environ["ARGOS_TRANSLATE_PACKAGE_DIR"] = spec["path"]
        import argostranslate.settings

        argostranslate.settings.package_dirs = [Path(spec["path"])]
        argostranslate.settings.chunk_type = argostranslate.settings.ChunkType.MINISBD
        import argostranslate.translate

        translated = argostranslate.translate.get_translation_from_codes(spec["source"], spec["target"]).translate("Hello.")
        assert translated.strip()
    else:
        raise ValueError("Неизвестная проверка компонента")
    return {"ok": True}


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
