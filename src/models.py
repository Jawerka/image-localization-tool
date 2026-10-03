"""Модели данных для приложения."""

from dataclasses import dataclass, field
from PIL import Image


TRANSLATABLE_TYPES = frozenset({"dialogue", "narration", "title"})

_STROKE_MODES = frozenset({"auto", "none", "custom"})
_WARP_KINDS = frozenset({"none", "arc", "ring", "wave", "perspective", "mesh"})


def _clamp_channel(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(255, number))


def _clamp_rgb(values) -> tuple[int, int, int]:
    if not values:
        return (0, 0, 0)
    channels = list(values)[:3]
    while len(channels) < 3:
        channels.append(0)
    return (
        _clamp_channel(channels[0]),
        _clamp_channel(channels[1]),
        _clamp_channel(channels[2]),
    )


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _default_warp() -> dict:
    return {"kind": "none", "bend": 0.0, "quad": None, "mesh": None}


def _copy_points(value):
    """Список точек ``[x, y]`` или сетка рядами. Некорректные данные — None."""
    if not isinstance(value, (list, tuple)) or not value:
        return None
    rows = value
    first = value[0]
    if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
        rows = []
        for row in value:
            if not isinstance(row, (list, tuple)):
                return None
            rows.extend(row)
    points = []
    for point in rows:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            points.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            return None
    return points


def _normalize_warp(data) -> dict:
    """Привести варп к словарю. Неизвестный ``kind`` становится ``none``."""
    warp = _default_warp()
    if not isinstance(data, dict):
        return warp
    kind = str(data.get("kind") or "none").strip().lower()
    if kind not in _WARP_KINDS:
        kind = "none"
    bend = data.get("bend")
    warp["kind"] = kind
    warp["bend"] = _as_float(0.0 if bend is None else bend)
    warp["quad"] = _copy_points(data.get("quad"))
    warp["mesh"] = _copy_points(data.get("mesh"))
    return warp


@dataclass
class TextStyle:
    """Визуальный стиль блока: цвет, кегль, выравнивание, обводка и деформация.

    Старый словарь только с прежними ключами по-прежнему читается:
    новые поля получают исторические значения по умолчанию.
    """

    fill_rgb: tuple[int, int, int] = (0, 0, 0)
    stroke_rgb: tuple[int, int, int] | None = None
    font_size: int = 16
    alignment: str = "center"
    uppercase: bool = False
    line_height: int = 18
    font_size_override: int = 0
    font_id: str = ""
    stroke_mode: str = "auto"  # auto|none|custom
    stroke_width: float = 0.0
    letter_spacing: float = 0.0
    line_spacing: float = 0.0
    rotation: float = 0.0  # градусы, против часовой
    skew_x: float = 0.0  # градусы
    warp: dict = field(default_factory=_default_warp)

    def __post_init__(self) -> None:
        self.fill_rgb = _clamp_rgb(self.fill_rgb)
        if self.stroke_rgb is not None:
            self.stroke_rgb = _clamp_rgb(self.stroke_rgb)
        mode = str(self.stroke_mode or "auto").strip().lower()
        self.stroke_mode = mode if mode in _STROKE_MODES else "auto"
        self.font_id = str(self.font_id or "")
        self.stroke_width = _as_float(self.stroke_width)
        self.letter_spacing = _as_float(self.letter_spacing)
        self.line_spacing = _as_float(self.line_spacing)
        self.rotation = _as_float(self.rotation)
        self.skew_x = _as_float(self.skew_x)
        self.warp = _normalize_warp(self.warp)

    def to_dict(self) -> dict:
        warp = _normalize_warp(self.warp)
        return {
            "fill_rgb": [int(v) for v in self.fill_rgb],
            "stroke_rgb": [int(v) for v in self.stroke_rgb] if self.stroke_rgb else None,
            "font_size": int(self.font_size),
            "alignment": self.alignment,
            "uppercase": bool(self.uppercase),
            "line_height": int(self.line_height),
            "font_size_override": int(self.font_size_override),
            "font_id": self.font_id,
            "stroke_mode": self.stroke_mode,
            "stroke_width": self.stroke_width,
            "letter_spacing": self.letter_spacing,
            "line_spacing": self.line_spacing,
            "rotation": self.rotation,
            "skew_x": self.skew_x,
            "warp": {
                "kind": warp["kind"],
                "bend": warp["bend"],
                "quad": warp["quad"],
                "mesh": warp["mesh"],
            },
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "TextStyle":
        if not data:
            return cls()
        fill = data.get("fill_rgb") or (0, 0, 0)
        stroke = data.get("stroke_rgb")
        return cls(
            fill_rgb=tuple(fill),
            stroke_rgb=tuple(stroke) if stroke else None,
            font_size=int(data.get("font_size", 16)),
            alignment=str(data.get("alignment", "center")),
            uppercase=bool(data.get("uppercase", False)),
            line_height=int(data.get("line_height", 18)),
            font_size_override=int(data.get("font_size_override", 0)),
            font_id=str(data.get("font_id") or ""),
            stroke_mode=str(data.get("stroke_mode") or "auto"),
            stroke_width=_as_float(data.get("stroke_width", 0.0)),
            letter_spacing=_as_float(data.get("letter_spacing", 0.0)),
            line_spacing=_as_float(data.get("line_spacing", 0.0)),
            rotation=_as_float(data.get("rotation", 0.0)),
            skew_x=_as_float(data.get("skew_x", 0.0)),
            warp=data.get("warp") if isinstance(data.get("warp"), dict) else _default_warp(),
        )


@dataclass
class TextRegion:
    """Регион текста страницы: баллон, строка или абзац."""

    id: int
    bbox: tuple[int, int, int, int]
    class_name: str = "text_free"
    confidence: float = 0.0
    text: str = ""
    translation: str = ""
    block_type: str = "dialogue"
    speaker: str = ""
    speaker_gender: str = ""
    bubble_bbox: tuple[int, int, int, int] | None = None
    order: int = 0
    style: TextStyle = field(default_factory=TextStyle)
    skip: bool = False
    manual: bool = False
    edited: bool = False
    overflow: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bbox": [int(v) for v in self.bbox],
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "text": self.text,
            "translation": self.translation,
            "type": self.block_type,
            "speaker": self.speaker,
            "speaker_gender": self.speaker_gender,
            "bubble_bbox": [int(v) for v in self.bubble_bbox] if self.bubble_bbox else None,
            "order": self.order,
            "skip": self.skip,
            "manual": self.manual,
            "edited": self.edited,
            "overflow": self.overflow,
            "style": self.style.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextRegion":
        bubble = data.get("bubble_bbox")
        return cls(
            id=int(data["id"]),
            bbox=tuple(int(v) for v in data["bbox"]),
            class_name=str(data.get("class_name", "text_free")),
            confidence=float(data.get("confidence", 0.0)),
            text=str(data.get("text", "")),
            translation=str(data.get("translation", "")),
            block_type=str(data.get("type") or data.get("block_type") or "dialogue"),
            speaker=str(data.get("speaker", "")),
            speaker_gender=str(data.get("speaker_gender", "")),
            bubble_bbox=tuple(int(v) for v in bubble) if bubble else None,
            order=int(data.get("order", 0)),
            style=TextStyle.from_dict(data.get("style")),
            skip=bool(data.get("skip", False)),
            manual=bool(data.get("manual", False)),
            edited=bool(data.get("edited", False)),
            overflow=bool(data.get("overflow", False)),
        )


@dataclass
class MaskStroke:
    """Штрих кисти или ластика поверх маски букв."""

    mode: str
    radius: int
    points: list[tuple[int, int]]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "radius": int(self.radius),
            "points": [[int(x), int(y)] for x, y in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MaskStroke":
        mode = str(data.get("mode") or "")
        if mode not in ("paint", "erase"):
            raise ValueError(f"Некорректный режим штриха: {mode}")
        points = [(int(point[0]), int(point[1])) for point in data.get("points") or []]
        return cls(mode=mode, radius=int(data.get("radius") or 0), points=points)


def should_translate(region: TextRegion, translate_sfx: bool = False) -> bool:
    """Диалоги, подписи и заголовки переводятся. SFX — только по флагу."""
    if region.skip:
        return False
    if not region.text or not region.text.strip():
        return False
    if region.block_type in TRANSLATABLE_TYPES:
        return True
    return bool(translate_sfx and region.block_type == "sfx")


@dataclass
class PageResult:
    """Результат пайплайна v2."""

    source_path: str
    output_image: Image.Image
    regions: list[TextRegion] = field(default_factory=list)
    reading_direction: str = "ltr"
    warnings: list[str] = field(default_factory=list)
    stages_completed: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    ocr_engine: str = ""
    translator_engine: str = ""

    def save(self, path: str) -> None:
        """Сохранить изображение."""
        self.output_image.save(path)

    def regions_payload(self) -> dict:
        """Сериализуемый снимок OCR, перевода и говорящих."""
        return {
            "source_path": self.source_path,
            "reading_direction": self.reading_direction,
            "ocr_engine": self.ocr_engine,
            "translator_engine": self.translator_engine,
            "timings": self.timings,
            "warnings": list(self.warnings),
            "regions": [region.to_dict() for region in self.regions],
        }

    @property
    def translation_pairs(self) -> list[tuple[str, str]]:
        """Пары (оригинал, перевод) в порядке чтения."""
        ordered = sorted(self.regions, key=lambda item: item.order)
        return [(region.text, region.translation) for region in ordered if region.text]
