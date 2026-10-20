"""Проверка чистой portable без манифест-зеркала и скрытых зависимостей."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.app.downloads import atomic_json, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", required=True)
    parser.add_argument("--cuda", action="store_true")
    parser.add_argument("--stage", default="", help="проверить обновление существующей изолированной portable")
    args = parser.parse_args()
    portable = ROOT / args.portable
    stage = ROOT / args.stage if args.stage else ROOT / "build" / ("frozen-smoke-" + digest(portable)[:12])
    if not stage.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Каталог smoke должен находиться внутри build")
    stage.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(portable) as archive:
        for info in archive.infolist():
            path = stage / info.filename
            if not path.resolve().is_relative_to(stage.resolve()):
                raise ValueError("Недопустимый путь в portable")
        archive.extractall(stage)
    matches = [p for p in stage.rglob("ImageLocalizationTool.exe") if p.parent.name == "sidecar"]
    if len(matches) != 1:
        raise ValueError("Нет единственного frozen-sidecar")
    exe = matches[0]
    app = exe.parent.parent
    (app / "data").mkdir(exist_ok=True)
    env = dict(os.environ)
    for key in ("ILT_RUNTIME_MANIFEST_URL", "ILT_COMPONENT_ROOT", "ILT_INSTALL_ROOT", "ILT_DATA_DIR"):
        env.pop(key, None)
    env["ILT_SKIP_KEYRING_MIGRATION"] = "1"
    # CLI-сайдкар в sidecar/: минимальный marker определяет корень переносимой раскладки.
    command = [str(exe), "--deploy", "cpu" if not args.cuda else "cuda"]
    print("Frozen runtime smoke:", "CPU" if not args.cuda else "CUDA", flush=True)
    result = subprocess.run(command, cwd=app, env=env, timeout=3600)
    if result.returncode:
        return result.returncode
    print("Runtime установлен и проверен чистым frozen-процессом", flush=True)
    # Подготовка полного offline-набора на CPU, без выбора GPU из железа разработчика.
    request = app / "offline-smoke.json"
    atomic_json(request, {"kind": "prepare-offline", "device": "cuda" if args.cuda else "cpu"})
    result = subprocess.run([str(exe), "--component-check", str(request)], cwd=app, env=env, timeout=3600)
    if result.returncode:
        return result.returncode
    print("Frozen OCR/Argos/MiniSBD/LaMa готовы", flush=True)
    atomic_json(request, {"kind": "offline-functional", "device": "cuda" if args.cuda else "cpu",
                          "path": str(app / "data" / "offline-source.png")})
    result = subprocess.run([str(exe), "--component-check", str(request)], cwd=app, env=env, timeout=300)
    if result.returncode:
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
