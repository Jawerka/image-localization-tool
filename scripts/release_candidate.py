"""Неизменяемый комплект релиза: каталог, исходники, артефакты и ручная приёмка."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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

# open — критерий не выполнен; такой пункт публикацию не пропускает.
CHECK_STATUSES = frozenset({
    "implemented", "tested", "accepted", "superseded", "deferred", "open",
})
REQUIRED_PASS_STATUSES = frozenset({"tested", "accepted"})
REQUIRED_PASS_RESULTS = frozenset({"ok", "pass", "passed", "accepted"})
LEGACY_ACCEPTANCE_VERSIONS = frozenset({"1.0.5", "1.1.0"})
PASSPORT_KIND = "ilt-acceptance-passport"
REQUIRED_CHECK_IDS = [
    "T01", "T03", "T04", "T06", "Q01", "C03",
    "U07", "Q02", "Q05", "U08", "T02", "Q06",
    "T05", "H02", "P07", "P08", "P09", "P02", "P01", "P03", "P04", "P05",
    "H01", "H03",
]


def validate_passport(
    passport: dict,
    *,
    source_sha: str,
    version: str,
    artifact_sha256: str | None = None,
    required_ids: list[str] | None = None,
    assets: list[dict] | None = None,
    image_digest: str | None = None,
) -> None:
    """Отказать, если паспорт не относится к этому SHA/версии или обязательное не принято."""
    if not isinstance(passport, dict):
        raise ValueError("Паспорт должен быть объектом")
    if str(passport.get("kind") or "") != PASSPORT_KIND:
        raise ValueError("Ожидался паспорт приёмки кандидата")
    recorded_version = str(passport.get("version") or "")
    if recorded_version in LEGACY_ACCEPTANCE_VERSIONS:
        raise ValueError("Результаты старых приёмок 1.0.5/1.1.0 не засчитываются")
    if recorded_version != str(version):
        raise ValueError("Версия паспорта не совпадает с кандидатом")
    recorded_sha = str(passport.get("source_sha") or "")
    if recorded_sha != str(source_sha):
        raise ValueError("SHA исходников паспорта не совпадает с кандидатом")
    if assets is not None:
        recorded_assets = passport.get("assets")
        if not isinstance(recorded_assets, list) or not recorded_assets:
            raise ValueError("В паспорте нет полного списка контрольных сумм")
        expected = {(item["name"], item["sha256"], item["size"]) for item in assets}
        recorded = {(item.get("name"), item.get("sha256"), item.get("size")) for item in recorded_assets}
        if expected != recorded:
            raise ValueError("Набор SHA256 паспорта не совпадает с кандидатом")
        checksums = {item["sha256"] for item in assets}
        if artifact_sha256 is not None and artifact_sha256 not in checksums:
            raise ValueError("SHA256 артефакта не входит в комплект кандидата")
        recorded_single = str(passport.get("artifact_sha256") or "")
        if recorded_single and recorded_single not in checksums:
            raise ValueError("SHA256 артефакта паспорта не совпадает с кандидатом")
    elif artifact_sha256 is not None:
        recorded_artifact = str(passport.get("artifact_sha256") or "")
        if recorded_artifact != str(artifact_sha256):
            raise ValueError("SHA256 артефакта паспорта не совпадает с кандидатом")
    if image_digest is not None:
        recorded_digest = str(passport.get("image_digest") or "").strip()
        if recorded_digest != str(image_digest).strip():
            raise ValueError("Digest образа паспорта не совпадает с кандидатом")
    checks = passport.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("В паспорте нет проверок")
    by_id: dict[str, dict] = {}
    for item in checks:
        if not isinstance(item, dict):
            raise ValueError("Запись проверки должна быть объектом")
        check_id = str(item.get("id") or "").strip()
        if not check_id:
            raise ValueError("У проверки нет id")
        status = str(item.get("status") or "").strip()
        if status not in CHECK_STATUSES:
            raise ValueError(f"Неизвестный статус проверки: {status}")
        by_id[check_id] = item
    for check_id in required_ids or []:
        item = by_id.get(check_id)
        if item is None:
            raise ValueError(f"Нет обязательной проверки: {check_id}")
        status = str(item.get("status") or "")
        result = str(item.get("result") or "").strip().lower()
        if status not in REQUIRED_PASS_STATUSES:
            raise ValueError(f"Обязательная проверка {check_id} не принята: {status}")
        if result not in REQUIRED_PASS_RESULTS:
            raise ValueError(f"Обязательная проверка {check_id} провалена или пропущена")


def source_digest(root: Path) -> str:
    paths = []
    for name in ("src", "scripts", "web", "extension", "locks", "assets", "installer", ".github/workflows", "apps/desktop/lib", "apps/desktop/windows"):
        folder = root / name
        paths += [p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and "node_modules" not in p.parts and "ephemeral" not in p.parts
                  and p.suffix not in (".pyc", ".log")]
    paths += list(root.glob("requirements*.txt"))
    paths += [root / "apps/desktop/pubspec.yaml", root / "apps/desktop/pubspec.lock"]
    paths.append(root / "ImageLocalizationTool.spec")
    paths += [root / n for n in ("Dockerfile", ".dockerignore", "compose.yaml", "compose.ghcr.yaml", "requirements-container.lock")]
    return hashlib.sha256(json.dumps([(p.relative_to(root).as_posix(), digest(p))
                                     for p in sorted(set(paths)) if p.is_file()]).encode()).hexdigest()


def embedded_catalogs(path: Path, *, prepared: bool = False) -> dict[str, bytes]:
    names = ("runtime_manifest.json", "component_manifest.json")
    found = {}
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            forbidden = (".downloads",) if prepared else (".resources", ".downloads", ".builtin")
            if any(part in n.split("/") for n in archive.namelist() for part in forbidden):
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
    required = [f"ImageLocalizationTool-{version}-windows-x64-portable.zip",
                f"ImageLocalizationTool-{version}-server-win64.zip",
                f"ImageLocalizationTool-{version}-server-linux-x64.tar.gz",
                f"ilt-runtime-manifest-{version}.json", f"ilt-component-manifest-{version}.json",
                f"ilt-extension-chromium-{version}.zip", f"ilt-extension-firefox-{version}.zip",
                f"ImageLocalizationTool-{version}-windows-x64-portable-cpu-full.zip",
                f"ImageLocalizationTool-{version}-docker-cpu-full.zip", "GHCR-DIGEST.txt", "compose.ghcr.yaml"]
    missing = [name for name in required if not (assets / name).is_file()]
    if missing:
        raise ValueError("Неполный комплект релиза: " + ", ".join(missing))
    image_digest = (assets / "GHCR-DIGEST.txt").read_text().strip()
    if not re.fullmatch(r"ghcr\.io/jawerka/image-localization-tool@sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("Нет закреплённого digest опубликованного Docker-образа")
    verify_build(root, assets)
    catalogs = {name: (root / "src/app" / name).read_bytes()
                for name in ("runtime_manifest.json", "component_manifest.json")}
    for released, bundled in ((f"ilt-runtime-manifest-{version}.json", "runtime_manifest.json"),
                              (f"ilt-component-manifest-{version}.json", "component_manifest.json")):
        if (assets / released).read_bytes() != catalogs[bundled]:
            raise ValueError("Релизный и встроенный каталоги различаются")
    for name in required:
        if name.startswith("ImageLocalizationTool-") and name.endswith((".zip", ".tar.gz")) and "-docker-" not in name:
            if embedded_catalogs(assets / name, prepared="-cpu-full" in name) != catalogs:
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
    if proof.get("source_sha") != source_digest(root) or len(proof.get("assets", [])) != 2:
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
    parser.add_argument(
        "action",
        choices=("create", "verify", "approve", "stamp-build", "verify-build", "validate-passport"),
    )
    parser.add_argument("--assets", default="dist")
    parser.add_argument("--report", default="build/release-candidate.json")
    parser.add_argument("--tag", default="")
    parser.add_argument("--checks-passed", action="store_true")
    parser.add_argument("--complete-windows", action="store_true")
    parser.add_argument("--passport", default="")
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--artifact-sha256", default="")
    parser.add_argument("--candidate", default="")
    parser.add_argument("--required", action="append", default=[])
    args = parser.parse_args()
    path = ROOT / args.report
    assets = ROOT / args.assets
    try:
        if args.action == "validate-passport":
            passport_path = Path(args.passport)
            passport = json.loads(passport_path.read_text(encoding="utf-8"))
            report_assets = None
            image_digest = None
            artifact_sha = args.artifact_sha256 or None
            if args.candidate:
                report = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
                report_assets = list(report.get("assets") or [])
                digest_file = assets / "GHCR-DIGEST.txt"
                if digest_file.is_file():
                    image_digest = digest_file.read_text(encoding="utf-8").strip()
                if artifact_sha is None and report_assets:
                    artifact_sha = str(report_assets[0].get("sha256") or "")
            validate_passport(
                passport,
                source_sha=args.source_sha,
                version=args.version,
                artifact_sha256=artifact_sha,
                required_ids=list(args.required) or list(REQUIRED_CHECK_IDS),
                assets=report_assets,
                image_digest=image_digest,
            )
            print("Паспорт принят")
            return 0
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
                         ("windows-x64-portable.zip", "server-win64.zip")]
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
