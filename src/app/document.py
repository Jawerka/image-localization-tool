"""Документ страницы и план пересчёта после правки."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models import MaskStroke, TextRegion


@dataclass
class PageDocument:
    """Регионы, штрихи маски и служебные поля страницы."""

    version: int = 1
    regions: list[TextRegion] = field(default_factory=list)
    strokes: list[MaskStroke] = field(default_factory=list)
    reading_direction: str = "ltr"
    warnings: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    ocr_engine: str = ""
    translator_engine: str = ""

    def to_dict(self) -> dict:
        return {
            "version": int(self.version),
            "regions": [region.to_dict() for region in self.regions],
            "strokes": [stroke.to_dict() for stroke in self.strokes],
            "reading_direction": self.reading_direction or "ltr",
            "warnings": [str(item) for item in self.warnings],
            "timings": dict(self.timings),
            "ocr_engine": self.ocr_engine or "",
            "translator_engine": self.translator_engine or "",
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> PageDocument:
        """Прочитать документ. Старый ``regions.json`` без version и strokes тоже подходит."""
        if not isinstance(data, dict):
            return cls()
        regions = [
            TextRegion.from_dict(item)
            for item in data.get("regions") or []
            if isinstance(item, dict)
        ]
        strokes = [
            MaskStroke.from_dict(item)
            for item in data.get("strokes") or []
            if isinstance(item, dict)
        ]
        if "version" in data and data.get("version") is not None:
            version = int(data["version"])
        else:
            version = 1
        timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
        warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        direction = str(data.get("reading_direction") or "ltr")
        return cls(
            version=version,
            regions=regions,
            strokes=strokes,
            reading_direction=direction,
            warnings=[str(item) for item in warnings],
            timings=dict(timings),
            ocr_engine=str(data.get("ocr_engine") or ""),
            translator_engine=str(data.get("translator_engine") or ""),
        )


def diff_plan(previous: PageDocument, new: PageDocument) -> str:
    """Что пересчитать: ``none``, ``typeset`` или ``clean``.

    Сравнение по содержимому, поле ``version`` не учитывается.
    ``clean`` нужен, если менялись рамки, набор id, пропуск, тип блока,
    исходный текст, штрихи или страница потеряла либо получила регион.
    ``typeset`` — если изменились только перевод, стиль или говорящий.
    """
    if _strokes(previous) != _strokes(new):
        return "clean"
    previous_by_id = _by_id(previous.regions)
    new_by_id = _by_id(new.regions)
    if set(previous_by_id) != set(new_by_id):
        return "clean"

    typeset = previous.reading_direction != new.reading_direction
    for region_id, old in previous_by_id.items():
        current = new_by_id[region_id]
        if _needs_clean(old, current):
            return "clean"
        if _needs_typeset(old, current):
            typeset = True
    if typeset:
        return "typeset"
    return "none"


def _by_id(regions: list[TextRegion]) -> dict[int, TextRegion]:
    return {int(region.id): region for region in regions}


def _strokes(document: PageDocument) -> list[dict]:
    return [stroke.to_dict() for stroke in document.strokes]


def _box(value) -> tuple | None:
    if not value:
        return None
    return tuple(int(item) for item in value)


def _needs_clean(old: TextRegion, current: TextRegion) -> bool:
    return (
        _box(old.bbox) != _box(current.bbox)
        or _box(old.bubble_bbox) != _box(current.bubble_bbox)
        or bool(old.skip) != bool(current.skip)
        or old.block_type != current.block_type
        or old.text != current.text
    )


def _needs_typeset(old: TextRegion, current: TextRegion) -> bool:
    return (
        old.translation != current.translation
        or old.speaker != current.speaker
        or old.speaker_gender != current.speaker_gender
        or old.style.to_dict() != current.style.to_dict()
    )
