"""Фиксированный каталог моделей, языков, OCR и шрифтов с проверенной установкой."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from src.app import downloads
from src.utils.paths import components_root, install_root, project_root


@dataclass(frozen=True)
class Component:
    id: str
    title: str
    kind: str
    files: tuple[downloads.Artifact, ...]
    check: str = ""
    source: str = ""
    target: str = ""

    @property
    def revision(self):
        data = [self.id, self.kind, self.source, self.target,
                [(f.name, f.sha256, f.size_bytes) for f in self.files]]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()

    @property
    def size_bytes(self):
        return sum(f.size_bytes for f in self.files)


def load(path: Path | None = None) -> list[Component]:
    path = path or Path(__file__).with_name("component_manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("Неизвестная версия каталога ресурсов")
    result = []
    for raw in data["components"]:
        if not re.fullmatch(r"[a-z0-9-]+", raw["id"]):
            raise ValueError("Недопустимое имя компонента")
        files = tuple(downloads.Artifact(f["name"], (f["url"], *f.get("mirrors", [])), f["sha256"], f["size_bytes"])
                      for f in raw["files"])
        if not files or len({f.name for f in files}) != len(files) or raw["id"] in {c.id for c in result}:
            raise ValueError("Неверный состав компонента")
        result.append(Component(raw["id"], raw["title"], raw["kind"], files, raw.get("check", ""),
                                raw.get("source", ""), raw.get("target", "")))
    return result


def by_id(component_id: str) -> Component:
    return next(c for c in load() if c.id == component_id)


def store_root() -> Path:
    return components_root() / ".resources"


def directory(component: Component) -> Path:
    """Проверить значение указателя прежде, чем использовать его как путь."""
    active = store_root() / ".active" / f"{component.id}.json"
    try:
        rev = json.loads(active.read_text(encoding="utf-8"))["revision"]
        if re.fullmatch(r"[0-9a-f]{64}", rev):
            short = store_root() / component.id / rev[:24]
            full = store_root() / component.id / rev
            return full if full.is_dir() and not short.exists() else short
    except (OSError, ValueError, KeyError, TypeError):
        pass
    previous_root = os.environ.get("ILT_COMPONENT_PREVIOUS_ROOT", "")
    if previous_root:
        previous = Path(previous_root) / ".resources"
        try:
            rev = json.loads((previous / ".active" / f"{component.id}.json").read_text())["revision"]
            if re.fullmatch(r"[0-9a-f]{64}", rev):
                short = previous / component.id / rev[:24]
                full = previous / component.id / rev
                return full if full.is_dir() and not short.exists() else short
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return store_root() / component.id / component.revision[:24]


def ready(component: Component, ignore_checker: bool = False) -> bool:
    folder = directory(component)
    try:
        data = json.loads((folder / "component.json").read_text(encoding="utf-8"))
        if data.get("revision") != component.revision or data.get("checked") is not True:
            return False
        from src.app.component_check import validation_identity

        if component.check and not ignore_checker and data.get("checker") != validation_identity():
            return False
        for name, record in data["inventory"].items():
            path = safe_path(folder, name)
            stat = path.stat()
            if stat.st_size != record["size"] or (stat.st_mtime_ns != record["mtime"]
                                                 and downloads.digest(path) != record["sha256"]):
                return False
        return bool(data["inventory"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def safe_path(root: Path, name: str) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or ":" in name or not pure.parts:
        raise ValueError("Недопустимый путь в компоненте")
    return root.joinpath(*pure.parts)


def installed_file(filename: str) -> Path | None:
    """Разрешить путь внешнего файла без запуска загрузки."""
    for component in load():
        if component.kind != "language" and filename in {f.name for f in component.files}:
            path = directory(component) / filename
            if ready(component) and path.is_file():
                return path
    return None


def language_dirs() -> list[Path]:
    return [directory(c) for c in load() if c.kind == "language" and ready(c)]


def ocr_params() -> dict:
    component = by_id("rapidocr")
    if not ready(component):
        raise RuntimeError("Нужно подготовить оффлайн-распознавание в настройках приложения")
    folder = directory(component)
    return {"Det.model_path": str(folder / "PP-OCRv6_det_small.onnx"),
            "Rec.model_path": str(folder / "PP-OCRv6_rec_small.onnx"),
            "Cls.model_path": str(folder / "ch_ppocr_mobile_v2.0_cls_mobile.onnx")}


def _seed(item: downloads.Artifact, cache: Path, override: str = "") -> None:
    """Проверенные прежние файлы переиспользуются без физической миграции пользователя."""
    target = cache / f"{item.sha256}.blob"
    if target.exists():
        return
    candidates = [Path(override) / item.name] if override else []
    candidates += [components_root() / "models" / item.name, install_root() / "models" / item.name,
                   install_root() / "fonts" / item.name, project_root() / "src/resources/fonts" / item.name]
    for candidate in candidates:
        if downloads.valid(candidate, item):
            cache.mkdir(parents=True, exist_ok=True)
            downloads.ensure_space(cache, item.size_bytes)
            shutil.copyfile(candidate, target)
            return


def install(component: Component, progress=None, pause=None, models_override: str = "") -> Path:
    """Транзакционная установка группы файлов; старый указатель сохраняется при отказе."""
    with downloads.installer_lock():
        if ready(component):
            return directory(component)
        if ready(component, ignore_checker=True):
            folder = directory(component)
            if progress:
                progress(component.size_bytes, component.size_bytes, "checking", "")
            validate_component(component, folder)
            from src.app.component_check import validation_identity

            marker = folder / "component.json"
            data = json.loads(marker.read_text(encoding="utf-8"))
            data["checker"] = validation_identity()
            downloads.atomic_json(marker, data)
            return folder
        cache = downloads.cache_root()
        files = []
        done = 0
        for item in component.files:
            _seed(item, cache, models_override)
            path = downloads.fetch(item, cache, pause=pause, progress=lambda n, t: progress(
                done + n, component.size_bytes, "downloading", "") if progress else None)
            files.append(path)
            done += item.size_bytes
        final = store_root() / component.id / component.revision[:24]
        stage = final.with_name(final.name + ".tmp")
        needed = component.size_bytes
        if component.kind == "language":
            with zipfile.ZipFile(files[0]) as archive:
                needed = sum(i.file_size for i in archive.infolist()) + component.files[1].size_bytes
        downloads.ensure_space(final.parent, needed)
        downloads.check_pause(pause)
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        try:
            if progress:
                progress(done, component.size_bytes, "installing", "")
            if component.kind == "language":
                with zipfile.ZipFile(files[0]) as archive:
                    for info in archive.infolist():
                        path = safe_path(stage, info.filename)
                        if info.is_dir():
                            continue
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(info) as source, path.open("wb") as dest:
                            shutil.copyfileobj(source, dest, downloads.CHUNK)
                roots = list(stage.glob("*/metadata.json"))
                if len(roots) != 1:
                    raise ValueError("Неверный архив языковой модели")
                meta = json.loads(roots[0].read_text(encoding="utf-8"))
                if meta.get("from_code") != component.source or meta.get("to_code") != component.target:
                    raise ValueError("Языки архива не совпадают с каталогом")
                sbd = roots[0].parent / "minisbd" / component.files[1].name
                sbd.parent.mkdir()
                shutil.copyfile(files[1], sbd)
            else:
                for item, cached in zip(component.files, files):
                    shutil.copyfile(cached, stage / item.name)
            if progress:
                progress(done, component.size_bytes, "checking", "")
            validate_component(component, stage)
            inventory = {}
            for path in stage.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    inventory[path.relative_to(stage).as_posix()] = {
                        "size": stat.st_size, "mtime": stat.st_mtime_ns, "sha256": downloads.digest(path)}
            from src.app.component_check import validation_identity

            downloads.atomic_json(stage / "component.json", {"id": component.id, "revision": component.revision,
                "checked": True, "inventory": inventory, "checker": validation_identity()})
            downloads.check_pause(pause)
            if final.exists():
                old_marker = final / "component.json"
                if old_marker.is_file() and json.loads(old_marker.read_text(encoding="utf-8")).get("revision") != component.revision:
                    raise RuntimeError("Конфликт каталога ревизии ресурса")
                previous = final.with_name(final.name + ".old")
                if previous.exists():
                    raise RuntimeError("Предыдущая попытка восстановления требует перезапуска")
                final.replace(previous)
                try:
                    stage.replace(final)
                except Exception:
                    previous.replace(final)
                    raise
                shutil.rmtree(previous, ignore_errors=True)
            else:
                stage.replace(final)
            downloads.atomic_json(store_root() / ".active" / f"{component.id}.json", {"revision": component.revision, "activated_at": time.time()})
            return final
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def validate_component(component: Component, folder: Path) -> None:
    """Повторная проверка новой базы не требует архива или повторной загрузки весов."""
    if not component.check:
        return
    from src.app.component_check import probe

    spec = {"kind": component.check, "path": str(folder / component.files[0].name)}
    if component.kind == "language":
        spec.update(path=str(folder), source=component.source, target=component.target)
    elif component.check == "rapidocr":
        spec["params"] = {"Det.model_path": str(folder / component.files[0].name),
                          "Rec.model_path": str(folder / component.files[1].name),
                          "Cls.model_path": str(folder / component.files[2].name)}
    probe(spec)
