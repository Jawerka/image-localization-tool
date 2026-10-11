"""CLI ``--deploy``: неинтерактивная установка компонентов (серверный режим).

``models`` — детектор, LaMa и шрифты; ``cpu``/``cuda``/``argos`` — паки
рантайма; ``all`` — модели, Argos и torch по рекомендации железа. Повторный
запуск идемпотентен, код возврата 0/1.
"""

from __future__ import annotations

import sys

from src.app import model_manager, runtime
from src.utils.logger import logger

TARGETS = ("cpu", "cuda", "argos", "models", "all")


def run(values: list[str]) -> int:
    """Развернуть указанные компоненты. 0 — всё хорошо, 1 — были ошибки."""
    targets = normalize(values)
    if not targets:
        print("Нечего разворачивать: укажите cpu, cuda, argos, models или all", file=sys.stderr)
        return 1
    failures: list[str] = []
    for target in targets:
        try:
            if target == "models":
                _deploy_models()
            else:
                _deploy_pack(_pack_id_for(target))
        except Exception as exc:
            logger.exception("Развёртывание %s не удалось", target)
            print(f"[{target}] ошибка: {exc}", file=sys.stderr)
            failures.append(target)
    if failures:
        print("Не удалось развернуть: " + ", ".join(failures), file=sys.stderr)
        return 1
    print("Готово.")
    return 0


def normalize(values: list[str]) -> list[str]:
    """``all`` раскрывается в models + argos + torch по железу, без дублей."""
    result: list[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if text == "all":
            expanded = ["models", "argos", recommended_torch()]
        elif text in TARGETS:
            expanded = [text]
        else:
            continue
        for item in expanded:
            if item not in result:
                result.append(item)
    return result


def recommended_torch() -> str:
    from src.app import hardware

    recommended = str(hardware.detect().get("recommended") or "torch-cpu")
    return "cuda" if recommended == "torch-cu128" else "cpu"


def _pack_id_for(target: str) -> str:
    mapping = {"cpu": "torch-cpu", "cuda": "torch-cu128", "argos": "argos"}
    return mapping[target]


def _deploy_pack(pack_id: str) -> None:
    pack = runtime.pack_by_id(pack_id)
    print(f"[{pack.id}] {pack.title} v{pack.version}")
    if runtime.is_installed(pack.id):
        print(f"[{pack.id}] уже установлено: {runtime.pack_dir(pack.id)}")
        runtime.activate_path(runtime.pack_dir(pack.id))
        return
    last_line = ""

    def progress(done, total, state, _message) -> None:
        nonlocal last_line
        if state == "downloading":
            megabytes = (done or 0) // (1024 * 1024)
            line = (
                f"[{pack.id}] {int(done * 100 / total)}% ({megabytes} МБ)"
                if total
                else f"[{pack.id}] {megabytes} МБ"
            )
            if line != last_line:
                last_line = line
                print(line, end="\r", flush=True)
        elif state == "installing":
            print(f"[{pack.id}] распаковка…")
        elif state == "installed":
            print(f"[{pack.id}] установлено в {runtime.pack_dir(pack.id)}")

    runtime.download_and_install(pack, progress)


def _deploy_models() -> None:
    print("[models] детектор, LaMa, шрифты")
    for kind in ("detector", "lama", "font"):
        try:
            dest = model_manager.dest_dir(kind)
            path = model_manager.download(kind, dest)
        except Exception as exc:
            raise RuntimeError(f"{kind}: {exc}") from exc
        print(f"[models] {kind}: {path}")
    try:
        model_manager.download_font_pack(model_manager.dest_dir("font"))
        print("[models] набор OFL-шрифтов: готово")
    except Exception as exc:
        print(f"[models] набор OFL-шрифтов не скачался: {exc}")
