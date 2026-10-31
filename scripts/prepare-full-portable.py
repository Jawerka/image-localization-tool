"""Подготовка полной portable в чистом staging без переноса пользовательских данных."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seed_components(source: Path, target: Path) -> None:
    """Переиспользовать только текущие ресурсы и CPU/Argos, без data и CUDA."""
    from src.app import component_catalog, runtime
    from src.app.downloads import atomic_json

    entries = [(".resources", component.id, component.revision, "component.json", False)
               for component in component_catalog.load()]
    entries += [("runtime", pack.id, pack.revision, "installed.json", True)
                for pack in runtime.platform_packs() if pack.id in {"torch-cpu", "argos"}]
    for category, name, revision, marker, is_runtime in entries:
        relative = Path(category) / (Path(".revisions") if is_runtime else Path()) / name
        candidates = [source / relative / revision[:24], source / relative / revision]
        folder = next((path for path in candidates if (path / marker).is_file()), None)
        if folder is None:
            continue
        info = json.loads((folder / marker).read_text(encoding="utf-8"))
        if info.get("revision") != revision:
            continue
        dest = target / relative / revision[:24]
        shutil.copytree(folder, dest, dirs_exist_ok=True)
        atomic_json(target / category / ".active" / f"{name}.json", {"revision": revision})
    atomic_json(target / "runtime" / ".active" / "torch.json", {"id": "torch-cpu"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--component-source", default="")
    args = parser.parse_args()
    stage = Path(args.stage).resolve()
    if stage == (ROOT / "build").resolve() or not stage.is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Полный stage должен быть отдельной папкой внутри build")
    if args.component_source:
        seed_components(Path(args.component_source).resolve(), stage)
    env = dict(os.environ)
    for key in ("ILT_RUNTIME_MANIFEST_URL", "ILT_COMPONENT_PREVIOUS_ROOT", "ARGOS_PACKAGES_DIR",
                "ARGOS_TRANSLATE_PACKAGE_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        env.pop(key, None)
    env.update(ILT_INSTALL_ROOT=str(stage), ILT_COMPONENT_ROOT=str(stage), ILT_DATA_DIR=str(stage / "data"))
    request = stage / "distribution-check.json"
    exe = stage / "sidecar" / "ImageLocalizationTool.exe"
    for kind in ("prepare-distribution", "verify-distribution", "functional-distribution"):
        request.write_text(json.dumps({"kind": kind, "path": str(stage / "data" / "offline-source.png")}), encoding="utf-8")
        print(kind, flush=True)
        result = subprocess.run([str(exe), "--component-check", str(request)], cwd=stage, env=env,
                                timeout=7200, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        response = stage / "check.result.json"
        data = json.loads(response.read_text(encoding="utf-8")) if response.is_file() else {}
        if result.returncode or data.get("ok") is not True:
            raise RuntimeError(data.get("error") or f"{kind}: код {result.returncode}, нет успешного результата")
    # Все проверки завершены. Эти каталоги принадлежат только проверенному build-stage.
    for name in ("data", ".downloads"):
        folder = stage / name
        if folder.exists():
            shutil.rmtree(folder)
    (stage / "data").mkdir()
    (stage / "data" / ".keep").touch()
    request.unlink(missing_ok=True)
    (stage / "check.result.json").unlink(missing_ok=True)
    (stage / ".installer.lock").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
