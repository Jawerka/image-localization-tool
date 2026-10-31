"""Глоссарий говорящих: сбор из регионов и нормализация записей.

Функции чистые, без файлов и сети. Список сохраняет хранилище проекта.

Ключи региона (``TextRegion.to_dict``): ``speaker``, ``speaker_gender``.
Запись глоссария: ``source``, ``target``, ``gender``, ``note``.

Сопоставление по ``source`` после ``strip`` чувствительно к регистру:
``Alice`` и ``alice`` — разные говорящие.

В ``project.json`` страница — это ``id``, ``source_path`` и ``name``, без
регионов. Регионы лежат в ``page.json`` у ``document.regions``
(``PageDocument.to_dict`` кладёт их и на верхний уровень ``regions``).
``glossary_from_pages`` читает ``page["regions"]``, затем
``page["document"]["regions"]``. Плоский список регионов передают
в ``merge_glossary``.
"""

from __future__ import annotations


def _text(value: object, *, strip: bool = False) -> str:
    """Строковое поле. Нестрока — пустая строка."""
    if not isinstance(value, str):
        return ""
    return value.strip() if strip else value


def _entry(source: str, target: str = "", gender: str = "", note: str = "") -> dict:
    return {
        "source": source,
        "target": target,
        "gender": gender,
        "note": note,
    }


def normalize_glossary(entries: list[dict] | None) -> list[dict]:
    """Привести JSON-список к записям ``{source, target, gender, note}``.

    Пустой ``source`` (в том числе из пробелов) и не-словари отбрасываются.
    Пропущенные строки становятся ``""``. ``source`` и ``gender`` обрезаются
    ``strip``. Повтор ``source`` не затирает первую запись. Порядок первых
    вхождений сохраняется, без сортировки.
    """
    if not isinstance(entries, list):
        return []
    kept: list[dict] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = _text(item.get("source"), strip=True)
        if not source or source in seen:
            continue
        seen.add(source)
        kept.append(
            _entry(
                source,
                _text(item.get("target")),
                _text(item.get("gender"), strip=True),
                _text(item.get("note")),
            )
        )
    return kept


def merge_glossary(regions: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Собрать говорящих из регионов и слить с уже существующим глоссарием.

    Пустое имя ``speaker`` пропускается. Регион не-dict игнорируется.
    ``speaker_gender`` слегка нормализуется: ``strip``, нет поля — ``""``.

    Пол не прыгает: остаётся первый непустой. Непустой пол уже существующей
    записи не заменяется полом региона. Пустой пол записи заполняется первым
    непустым полом региона. ``target`` и ``note`` берутся из существующей
    записи; у нового говорящего они пустые. Записи, которых нет среди
    регионов, не выбрасываются.

    Весь список, включая только ручные записи, сортируется по
    ``(source.casefold(), source)``.
    """
    merged = normalize_glossary(existing)
    by_source = {entry["source"]: entry for entry in merged}
    if not isinstance(regions, list):
        regions = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        source = _text(region.get("speaker"), strip=True)
        if not source:
            continue
        gender = _text(region.get("speaker_gender"), strip=True)
        current = by_source.get(source)
        if current is None:
            current = _entry(source, gender=gender)
            by_source[source] = current
            merged.append(current)
            continue
        if not current["gender"] and gender:
            current["gender"] = gender
    return sorted(merged, key=lambda entry: (entry["source"].casefold(), entry["source"]))


def _regions_on_page(page: dict) -> list:
    """Регионы страницы: верхний список, затем вложенный документ."""
    found: list = []
    direct = page.get("regions")
    if isinstance(direct, list):
        found.extend(direct)
    document = page.get("document")
    if isinstance(document, dict):
        nested = document.get("regions")
        if isinstance(nested, list):
            found.extend(nested)
    return found


def glossary_from_pages(pages: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Глоссарий по словарям страниц.

    Подходят документ страницы (``regions``) и ``page.json``
    (``document.regions``). Запись из ``project.json`` регионов не содержит:
    от неё в глоссарий ничего не добавится. Не-dict пропускаются.
    На одной странице сначала читается ``regions``, потом ``document.regions``.
    """
    regions: list = []
    if isinstance(pages, list):
        for page in pages:
            if isinstance(page, dict):
                regions.extend(_regions_on_page(page))
    return merge_glossary(regions, existing)
