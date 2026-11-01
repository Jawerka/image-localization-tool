"""Операции проекта и пакета вне HTTP-маршрутов."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.app.portable_project import pack_project, unpack_project


def save_package(store, project_id: str, dest: Path, editor: dict | None = None):
    """Собрать переносимый пакет. HTTP-статусы задаёт вызывающий."""
    return pack_project(store, project_id, dest, editor=editor)


def load_package(store, package: Path):
    """Распаковать пакет в store. Текущий проект меняет вызывающий."""
    return unpack_project(store, package)


def folder_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def storage_report(store, *, active_export_ids: set[str] | None = None) -> dict:
    """Объём exports, packages и imports без удаления."""
    root = Path(store.root)
    exports = root / "exports"
    packages = root / "packages"
    imports = root / "imports"
    return {
        "root": str(root),
        "exports_bytes": folder_bytes(exports),
        "packages_bytes": folder_bytes(packages),
        "imports_bytes": folder_bytes(imports),
        "active_export_ids": sorted(active_export_ids or ()),
        "imports_policy": "Неиспользуемые imports не удаляются автоматически: они могут быть исходниками живого проекта.",
    }


def purge_finished_exports(store, *, keep_ids: set[str]) -> dict:
    """Удалить каталоги завершённых exports, кроме активных заданий."""
    root = Path(store.root) / "exports"
    removed = []
    if root.is_dir():
        for meta in root.glob("*.json"):
            job_id = meta.stem
            if job_id in keep_ids:
                continue
            try:
                payload = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            folder_id = str(payload.get("folder") or "")
            folder = root / folder_id
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
            try:
                meta.unlink()
            except OSError:
                pass
            removed.append(job_id)
    return {"removed": removed}
