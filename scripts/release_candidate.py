"""Неизменяемый комплект релиза: каталог, исходники, артефакты и ручная приёмка."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.smoke_dist import read_app_version
from src.app.downloads import atomic_json, digest


def source_digest(root: Path) -> str:
    paths = []
    for name in ("src", "scripts", "web", "extension", "locks", "assets", "installer", ".github/workflows", "apps/desktop/lib", "apps/desktop/windows"):
        folder = root / name
        paths += [p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and "node_modules" not in p.parts and p.suffix not in (".pyc", ".log")]
    paths += list(root.glob("requirements*.txt"))
    paths += [root / "apps/desktop/pubspec.yaml", root / "apps/desktop/pubspec.lock"]
    paths.append(root / "ImageLocalizationTool.spec")
    return hashlib.sha256(json.dumps([(p.relative_to(root).as_posix(), digest(p))
                                     for p in sorted(set(paths)) if p.is_file()]).encode()).hexdigest()


def embedded_catalogs(path: Path) -> dict[str, bytes]:
    names = ("runtime_manifest.json", "component_manifest.json")
    found = {}
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            if any(part in n.split("/") for n in archive.namelist() for part in (".resources", ".downloads", ".builtin")):
                raise ValueError("В архив попали установленные компоненты или кэш")
            for name in names:
                matches = [n for n in archive.namelist() if n.endswith("/src/app/" + name)]
                if len(matches) != 1:
                    raise ValueError(f"В {path.name} нет единственного встроенного {name}")
                found[name] = archive.read(matches[0])
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            if any(part in n.name.split("/") for n in archive.getmembers() for part in (".resources", ".downloads", ".builtin")):
                raise ValueError("В архив попали установленные компоненты или кэш")
            for name in names:
                matches = [n for n in archive.getmembers() if n.name.endswith("/src/app/" + name)]
                if len(matches) != 1:
                    raise ValueError(f"В {path.name} нет единственного встроенного {name}")
                found[name] = archive.extractfile(matches[0]).read()
    return found


def create(root: Path, assets: Path, version: str, tag: str, checks: bool = False) -> dict:
    required = [f"ImageLocalizationTool-{version}-windows-x64-setup.exe",
                f"ImageLocalizationTool-{version}-windows-x64-portable.zip",
                f"ImageLocalizationTool-{version}-server-win64.zip",
                f"ImageLocalizationTool-{version}-server-linux-x64.tar.gz",
                f"ilt-runtime-manifest-{version}.json", f"ilt-component-manifest-{version}.json",
                f"ilt-extension-chromium-{version}.zip", f"ilt-extension-firefox-{version}.zip"]
    missing = [name for name in required if not (assets / name).is_file()]
    if missing:
        raise ValueError("Неполный комплект релиза: " + ", ".join(missing))
    verify_build(root, assets)
    catalogs = {name: (root / "src/app" / name).read_bytes()
                for name in ("runtime_manifest.json", "component_manifest.json")}
    for released, bundled in ((f"ilt-runtime-manifest-{version}.json", "runtime_manifest.json"),
                              (f"ilt-component-manifest-{version}.json", "component_manifest.json")):
        if (assets / released).read_bytes() != catalogs[bundled]:
            raise ValueError("Релизный и встроенный каталоги различаются")
    for name in required:
        if name.startswith("ImageLocalizationTool-") and name.endswith((".zip", ".tar.gz")):
            if embedded_catalogs(assets / name) != catalogs:
                raise ValueError(f"Устаревший встроенный каталог: {name}")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    records = [{"name": name, "sha256": digest(assets / name), "size": (assets / name).stat().st_size}
               for name in required]
    return {"schema": 1, "version": version, "commit": commit, "source_sha": source_digest(root),
            "tag": tag, "catalogs": {n: hashlib.sha256(v).hexdigest() for n, v in catalogs.items()},
            "assets": records, "checks_passed": checks, "manual_smoke_passed": False}


def verify_build(root: Path, assets: Path) -> None:
    """Пропуск пересборки допустим только для подтверждённых исходников и архивов."""
    proof = json.loads((root / "build/build-source.json").read_text())
    if proof.get("source_sha") != source_digest(root) or len(proof.get("assets", [])) != 3:
        raise ValueError("Нет подтверждения сборки из текущих исходников. Пересоберите Windows.")
    for item in proof["assets"]:
        if Path(item["name"]).name != item["name"] or digest(assets / item["name"]) != item["sha256"]:
            raise ValueError("Файл Windows-сборки изменён после проверки")


def verify(root: Path, assets: Path, report: dict, require_smoke: bool = True) -> None:
    if not report.get("checks_passed"):
        raise ValueError("Нет подтверждения автоматических проверок")
    if require_smoke and not report.get("manual_smoke_passed"):
        raise ValueError("Сначала выполните ручную приёмку подготовленного комплекта")
    if report.get("source_sha") != source_digest(root):
        raise ValueError("Исходники изменились после подготовки релиза")
    if report.get("version") != read_app_version(root):
        raise ValueError("Версия изменилась после подготовки")
    for item in report["assets"]:
        name = item["name"]
        if Path(name).name != name:
            raise ValueError("Неверное имя артефакта")
        path = assets / name
        if not path.is_file() or path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
            raise ValueError("Изменён подготовленный файл: " + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify", "approve", "stamp-build", "verify-build"))
    parser.add_argument("--assets", default="dist")
    parser.add_argument("--report", default="build/release-candidate.json")
    parser.add_argument("--tag", default="")
    parser.add_argument("--checks-passed", action="store_true")
    parser.add_argument("--complete-windows", action="store_true")
    args = parser.parse_args()
    path = ROOT / args.report
    assets = ROOT / args.assets
    try:
        if args.action == "stamp-build":
            atomic_json(ROOT / "build/build-source.json", {"source_sha": source_digest(ROOT)})
            return 0
        if args.action == "verify-build":
            proof = json.loads((ROOT / "build/build-source.json").read_text())
            if proof["source_sha"] != source_digest(ROOT):
                raise ValueError("Исходники изменились во время сборки. Пересоберите кандидат.")
            if args.complete_windows:
                version = read_app_version(ROOT)
                names = [f"ImageLocalizationTool-{version}-{suffix}" for suffix in
                         ("windows-x64-setup.exe", "windows-x64-portable.zip", "server-win64.zip")]
                proof["assets"] = [{"name": n, "sha256": digest(assets / n)} for n in names]
            atomic_json(ROOT / "build/build-source.json", proof)
            return 0
        if args.action == "create":
            version = read_app_version(ROOT)
            report = create(ROOT, assets, version, args.tag or "v" + version, args.checks_passed)
            atomic_json(path, report)
            sums = "\n".join(f"{i['sha256']}  {i['name']}" for i in report["assets"]) + "\n"
            (assets / "SHA256SUMS.txt").write_text(sums, encoding="ascii")
        else:
            report = json.loads(path.read_text(encoding="utf-8"))
            verify(ROOT, assets, report, require_smoke=args.action != "approve")
            if args.action == "approve":
                report["manual_smoke_passed"] = True
                atomic_json(path, report)
        print("Комплект релиза проверен")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
