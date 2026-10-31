"""Общий подготовленный CPU-профиль для контейнера и полной portable."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from src.utils.paths import install_root


def selections() -> list[dict]:
    """CPU выбирается явно, независимо от GPU сборочной машины."""
    return [{"source_lang": source, "target_lang": target, "device": "cpu",
             "ocr_backend": "rapid", "translator_backend": "argos", "inpainter_backend": "lama"}
            for source, target in (("en", "ru"), ("ru", "en"))]


def verify() -> dict:
    """Только проверить готовность обоих направлений, ничего не устанавливать."""
    from src.app.preparation import plan

    plans = [plan(selection) for selection in selections()]
    for prepared in plans:
        if prepared["state"] != "ready" or prepared["total"] != 0 or not all(item["ready"] for item in prepared["items"]):
            raise RuntimeError("Полный CPU-профиль не подготовлен: " + str(prepared.get("selection", {})))
    return {"ok": True, "profile": "cpu-full", "plans": plans}


def prepare() -> dict:
    """Установить и проверить весь профиль штатным координатором подготовки."""
    from src.app import __version__
    from src.app.downloads import atomic_json
    from src.app.preparation import Manager

    for selection in selections():
        manager = Manager()
        manager.start(selection)
        while manager.busy():
            time.sleep(0.2)
        result = manager.current()
        if result["state"] != "ready":
            raise RuntimeError(result.get("error") or "Подготовка полного профиля не завершена")
    result = verify()
    atomic_json(install_root() / "distribution.json", {"schema": 1, "profile": "cpu-full", "version": __version__,
        "components": [{"id": item["id"], "revision": item["revision"]}
                       for prepared in result["plans"] for item in prepared["items"]]})
    return result


def seed_data(root: Path) -> None:
    """Первая полная установка получает офлайн-дефолты, существующая — свои настройки."""
    marker = install_root() / "distribution.json"
    path = root / "settings.json"
    if path.exists() or not marker.is_file():
        return
    if json.loads(marker.read_text(encoding="utf-8-sig")).get("profile") != "cpu-full":
        return
    from src.app.settings import AppSettings

    AppSettings(ocr_backend="rapid", translator_backend="argos", device="cpu",
                first_run_complete=True).save(path)


def functional(path: Path) -> dict:
    """Настоящий pipeline и оба языка с запрещёнными сетевыми запросами."""
    from src.app.component_check import check

    verify()
    result = check({"kind": "offline-functional", "device": "cpu", "path": str(path)})
    from src.components.translator import TranslatorService

    translator = TranslatorService()
    text = "Привет, мир!"
    translated = translator.translate_texts([text], "ru", "en").get(text, "")
    if translator.last_error or not translated.strip() or translated == text:
        raise RuntimeError(translator.last_error or "Перевод ru→en не работает")
    return {**result, "reverse_translation": translated}


def main() -> int:
    from src.app import runtime
    from src.app.paths import ensure_data_root

    runtime.startup()
    root = ensure_data_root()
    operation = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if operation == "prepare":
        result = prepare()
    elif operation == "verify":
        result = verify()
    elif operation == "functional":
        result = functional(root / "distribution-source.png")
    else:
        raise ValueError("Ожидается prepare, verify или functional")
    print(json.dumps({key: value for key, value in result.items() if key != "plans"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
