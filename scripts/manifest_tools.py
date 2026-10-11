"""Общие инструменты манифеста рантайма (schema 2).

Используются ``scripts/build-runtime-manifest.py`` (сборка релизного манифеста
и встроенной копии) и ``scripts/check_release.py`` (гейт релиза), чтобы правила
полноты жили в одном месте: сумма ``size_bytes``, 64-hex sha256 каждого файла,
непустые ``files[]`` у wheels-записей и sha256 у archive-записей.
"""

from __future__ import annotations

KIND_ORDER = {"torch": 0, "argos": 1}
_HEX = set("0123456789abcdef")


def is_sha256(text: str) -> bool:
    return len(text) == 64 and all(char in _HEX for char in text)


def _record_label(record: object, index: int) -> str:
    if isinstance(record, dict):
        return f"packs[{index}] ({record.get('id') or '?'}, {record.get('os') or '?'})"
    return f"packs[{index}]"


def validate_manifest(manifest: object) -> list[str]:
    """Проверить манифест schema 2; вернуть список проблем (пусто — ок)."""
    if not isinstance(manifest, dict):
        return ["манифест — не объект"]
    issues: list[str] = []
    if manifest.get("schema") != 2:
        issues.append(f"schema: ожидалось 2, получено {manifest.get('schema')!r}")
    packs = manifest.get("packs")
    if not isinstance(packs, list) or not packs:
        issues.append("packs: непустой список обязателен")
        return issues
    for index, record in enumerate(packs):
        label = _record_label(record, index)
        if not isinstance(record, dict):
            issues.append(f"{label}: запись — не объект")
            continue
        for field in ("id", "title", "kind", "os", "python"):
            if not str(record.get(field) or "").strip():
                issues.append(f"{label}: пустое поле {field}")
        files = record.get("files")
        if files is not None:
            issues.extend(_validate_wheels(label, record, files))
        else:
            sha = str(record.get("sha256") or "").strip().casefold()
            if not is_sha256(sha):
                issues.append(f"{label}: sha256 archive-записи не 64-hex")
            if not str(record.get("url") or "").strip():
                issues.append(f"{label}: пустой url archive-записи")
            try:
                size = int(record.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            if size <= 0:
                issues.append(f"{label}: size_bytes archive-записи <= 0")
    return issues


def _validate_wheels(label: str, record: dict, files: object) -> list[str]:
    issues: list[str] = []
    if not isinstance(files, list) or not files:
        return [f"{label}: files пуст"]
    names: set[str] = set()
    total = 0
    for index, item in enumerate(files):
        item_label = f"{label}.files[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{item_label}: не объект")
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        sha = str(item.get("sha256") or "").strip().casefold()
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if not name:
            issues.append(f"{item_label}: пустое имя")
        elif name in names:
            issues.append(f"{item_label}: дубль имени {name}")
        else:
            names.add(name)
        if not url:
            issues.append(f"{item_label}: пустой url")
        if not is_sha256(sha):
            issues.append(f"{item_label} ({name or '?'}): sha256 не 64-hex")
        if size <= 0:
            issues.append(f"{item_label} ({name or '?'}): size_bytes <= 0")
        total += size
    try:
        declared = int(record.get("size_bytes") or 0)
    except (TypeError, ValueError):
        declared = -1
    if declared != total:
        issues.append(f"{label}: size_bytes {declared} ≠ сумме файлов {total}")
    return issues


def build_manifest(version: str, records: list[dict], url_base: str) -> dict:
    """Записи сводки → манифест schema 2.

    Wheels-записи переносятся как есть (URL файлов абсолютные), archive-записи
    (legacy schema 1) получают URL ассета релиза по ``url_base``.
    """
    entries: list[dict] = []
    for record in records:
        files = record.get("files")
        if isinstance(files, list) and files:
            entry = {
                "id": str(record.get("id") or ""),
                "title": str(record.get("title") or record.get("id") or ""),
                "kind": str(record.get("kind") or ""),
                "os": str(record.get("os") or ""),
                "arch": str(record.get("arch") or "x64"),
                "python": str(record.get("python") or ""),
                "version": str(record.get("version") or ""),
                "format": "wheels",
                "size_bytes": int(record.get("size_bytes") or 0),
                "files": [dict(item) for item in files if isinstance(item, dict)],
            }
        else:
            filename = str(record.get("file") or "")
            if not filename:
                continue
            entry = {
                "id": str(record.get("id") or ""),
                "title": str(record.get("title") or record.get("id") or ""),
                "kind": str(record.get("kind") or ""),
                "os": str(record.get("os") or ""),
                "arch": str(record.get("arch") or "x64"),
                "python": str(record.get("python") or ""),
                "version": str(record.get("version") or ""),
                "url": f"{url_base}/v{version}/{filename}",
                "sha256": str(record.get("sha256") or ""),
                "size_bytes": int(record.get("size_bytes") or 0),
            }
        if record.get("driver_min") is not None:
            entry["driver_min"] = int(record["driver_min"])
        entries.append(entry)
    entries.sort(key=lambda item: (item["os"], KIND_ORDER.get(item["kind"], 9), item["id"]))
    return {"schema": 2, "app": version, "packs": entries}


def merge_entries(base: list[dict], overlay: list[dict]) -> list[dict]:
    """Слить записи манифеста по (id, os): новые перекрывают старые."""
    merged: list[dict] = [dict(entry) for entry in overlay]
    keys = {(item.get("id"), item.get("os")) for item in overlay}
    for entry in base:
        if (entry.get("id"), entry.get("os")) not in keys:
            merged.append(dict(entry))
    merged.sort(
        key=lambda item: (
            str(item.get("os")),
            KIND_ORDER.get(str(item.get("kind")), 9),
            str(item.get("id")),
        )
    )
    return merged
