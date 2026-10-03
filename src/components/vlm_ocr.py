"""OCR страницы через VLM: пронумерованные рамки и дочитывание пустых боксов."""

from __future__ import annotations

import difflib
import re

from PIL import Image, ImageDraw, ImageFont

from src.components.text_regions import assign_reading_order
from src.models import TextRegion
from src.utils.llm_client import LlmClient
from src.utils.logger import logger

BLOCK_TYPES = ("dialogue", "narration", "title", "sfx", "sign", "noise")

# Имена цветов уходят в промпт, поэтому они простые английские.
PALETTE: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("red", (220, 30, 30)),
    ("blue", (30, 90, 220)),
    ("green", (20, 150, 60)),
    ("orange", (230, 120, 20)),
    ("magenta", (200, 30, 160)),
    ("cyan", (20, 150, 170)),
    ("purple", (110, 50, 190)),
    ("brown", (140, 80, 30)),
)

# Совпадение кропа со страничным OCR. Ниже — номера рамок считаем сбитыми.
_MATCH_RATIO = 0.6

OCR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reading_direction": {"type": "string", "enum": ["ltr", "rtl"]},
        "order": {"type": "array", "items": {"type": "integer"}},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": list(BLOCK_TYPES)},
                },
                "required": ["id", "text", "type"],
            },
        },
    },
    "required": ["reading_direction", "order", "blocks"],
}

CROP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "type": {"type": "string", "enum": list(BLOCK_TYPES)},
    },
    "required": ["text", "type"],
}


def _box_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Зазор между боксами. 0, если они пересекаются."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    dx = max(0, max(a[0] - bx2, b[0] - ax2))
    dy = max(0, max(a[1] - by2, b[1] - ay2))
    return (dx * dx + dy * dy) ** 0.5


def _assign_colors(
    regions: list[TextRegion],
    page_size: tuple[int, int],
) -> dict[int, tuple[str, tuple[int, int, int]]]:
    """Цвет рамки. У пересекающихся и близких боксов цвета разные."""
    limit = 0.03 * max(page_size[0], page_size[1], 1)
    assigned: dict[int, tuple[str, tuple[int, int, int]]] = {}
    for region in regions:
        taken = {
            assigned[other.id][0]
            for other in regions
            if other.id in assigned and _box_gap(region.bbox, other.bbox) < limit
        }
        choice = PALETTE[0]
        for item in PALETTE:
            if item[0] not in taken:
                choice = item
                break
        assigned[region.id] = choice
    return assigned


def _scale_box(
    bbox: tuple[int, int, int, int],
    scale_x: float,
    scale_y: float,
) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    x1 = round(x * scale_x)
    y1 = round(y * scale_y)
    x2 = round((x + w) * scale_x)
    y2 = round((y + h) * scale_y)
    return (x1, y1, max(x1 + 1, x2), max(y1 + 1, y2))


def _label_font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_marked_page(
    image: Image.Image,
    regions: list[TextRegion],
    max_side: int | None = None,
) -> Image.Image:
    """Копия страницы с цветными рамками и номерами регионов.

    Длинная сторона сжимается до ``max_side``, чтобы метки пережили сжатие на сервере.
    """
    marked = image.convert("RGB").copy()
    if max_side and max(marked.size) > max_side:
        marked.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    src_w, src_h = image.size
    scale_x = marked.width / src_w if src_w else 1.0
    scale_y = marked.height / src_h if src_h else 1.0
    colors = _assign_colors(regions, (src_w, src_h))
    long_side = max(marked.size)
    stroke = max(2, round(0.003 * long_side))
    font = _label_font(max(18, round(0.025 * long_side)))
    draw = ImageDraw.Draw(marked)
    for region in regions:
        _name, rgb = colors[region.id]
        x1, y1, x2, y2 = _scale_box(region.bbox, scale_x, scale_y)
        draw.rectangle((x1, y1, x2, y2), outline=rgb, width=stroke)
        label = str(region.id)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        label_w = right - left + stroke * 2
        label_h = bottom - top + stroke * 2
        tx = min(x1, max(0, marked.width - label_w))
        ty = y1 - label_h
        if ty < 0:
            ty = y1
        draw.rectangle((tx, ty, tx + label_w, ty + label_h), fill=rgb)
        draw.text((tx + stroke - left, ty + stroke - top), label, fill=(255, 255, 255), font=font)
    return marked


def _norm_box(bbox: tuple[int, int, int, int], page_size: tuple[int, int]) -> list[int]:
    """Бокс в шкале 0–1000 относительно страницы: [x1, y1, x2, y2]."""
    width, height = page_size
    width = max(width, 1)
    height = max(height, 1)
    x, y, w, h = bbox
    return [
        round(1000 * x / width),
        round(1000 * y / height),
        round(1000 * (x + w) / width),
        round(1000 * (y + h) / height),
    ]


def _prompt(
    regions: list[TextRegion],
    reading_order: str,
    colors: dict[int, tuple[str, tuple[int, int, int]]],
    page_size: tuple[int, int],
) -> str:
    hint = ""
    if reading_order in ("ltr", "rtl"):
        hint = f" The page reading direction is {reading_order}."
    lines = "\n".join(
        f"{region.id} ({colors[region.id][0]}): {_norm_box(region.bbox, page_size)}"
        for region in regions
    )
    return (
        "You are reading a comic or document page. Colored numbered boxes mark text regions. "
        "Each box has a label with its id on a background of the same color. "
        "Coordinates are [x1, y1, x2, y2] on a 0-1000 scale of the page. "
        "The id is the number printed on the label of that color. "
        "Do not renumber the boxes in reading order. "
        "Read each box in the original language. Do not translate and do not invent text "
        "outside the boxes."
        f"{hint}\n\n"
        "type is one of: dialogue (speech or thought balloon), narration (captions and "
        "paragraphs), title (headings), sfx (sound effects, including stylized words like "
        "GROWL, SWOOO, SILENCE), sign (text printed on objects: book spines, labels, "
        "screens), noise (a box with no real text).\n"
        "Keep the original wording. Join wrapped lines with spaces.\n"
        "Return every id.\n\n"
        f"Boxes:\n{lines}"
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _texts_match(page_text: str, crop_text: str) -> bool:
    left = _normalize_text(page_text)
    right = _normalize_text(crop_text)
    if not left or not right:
        return left == right
    return difflib.SequenceMatcher(None, left, right).ratio() >= _MATCH_RATIO


class VlmOcr:
    """Два запроса на страницу: баллоны, затем свободный текст.

    Пустые и сомнительные боксы дочитываются по кропу.
    """

    def __init__(self, client: LlmClient, reread_confidence: float = 0.5, max_side: int = 1536):
        self.client = client
        self.reread_confidence = reread_confidence
        self.max_side = max_side
        self.warnings: list[str] = []

    def recognize(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        reading_order: str = "auto",
    ) -> tuple[str, list[TextRegion]]:
        self.warnings = []
        if not regions:
            return "ltr", regions

        bubbles = [region for region in regions if region.bubble_bbox is not None]
        free = [region for region in regions if region.bubble_bbox is None]
        direction = "ltr"
        if bubbles:
            direction = self._recognize_pass(image, bubbles, reading_order, "баллоны")
        if free:
            free_direction = self._recognize_pass(image, free, reading_order, "свободный текст")
            if not bubbles:
                direction = free_direction
        if direction not in ("ltr", "rtl"):
            direction = "rtl" if reading_order == "rtl" else "ltr"
        assign_reading_order(regions, direction)
        logger.info(f"VLM OCR: {sum(1 for r in regions if r.text)} non-empty blocks, {direction}")
        return direction, regions

    def _recognize_pass(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        reading_order: str,
        pass_name: str,
    ) -> str:
        """Один проход. Один регион читается кропом, без страничного запроса."""
        if len(regions) == 1:
            self.read_crop(image, regions[0])
            return "ltr"
        colors = _assign_colors(regions, image.size)
        marked = draw_marked_page(image, regions, max_side=self.max_side)
        payload = self.client.chat_json(
            prompt=_prompt(regions, reading_order, colors, image.size),
            schema=OCR_SCHEMA,
            schema_name="page_ocr",
            images=[marked],
        )
        returned = self._apply_blocks(regions, payload.get("blocks") or [])
        self._reread_suspicious(image, regions, returned)
        self._reread_empty(image, regions)
        self._verify_pass(image, regions, pass_name)
        direction = str(payload.get("reading_direction") or "ltr").lower()
        return direction if direction in ("ltr", "rtl") else "ltr"

    def _apply_blocks(self, regions: list[TextRegion], blocks: list) -> set[int]:
        by_id = {region.id: region for region in regions}
        returned: set[int] = set()
        for block in blocks:
            try:
                region_id = int(block.get("id"))
            except (TypeError, ValueError):
                continue
            region = by_id.get(region_id)
            if region is None:
                continue
            returned.add(region_id)
            region.text = str(block.get("text") or "").strip()
            block_type = str(block.get("type") or "").strip().lower()
            if block_type in BLOCK_TYPES:
                region.block_type = block_type
        return returned

    def _reread_suspicious(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        returned: set[int],
    ) -> None:
        """Кроп для пропущенных id и для одинакового непустого текста."""
        counts: dict[str, list[TextRegion]] = {}
        for region in regions:
            text = region.text.strip()
            if text:
                counts.setdefault(text, []).append(region)
        duplicated = {
            region.id
            for group in counts.values()
            if len(group) > 1
            for region in group
        }
        for region in regions:
            if region.id not in returned or region.id in duplicated:
                self.read_crop(image, region)

    def _verify_pass(self, image: Image.Image, regions: list[TextRegion], pass_name: str) -> None:
        """Сверить первый и последний непустой бокс с кропом. Иначе перечитать проход."""
        filled = [region for region in sorted(regions, key=lambda item: item.id) if region.text.strip()]
        if not filled:
            return
        sample = [filled[0]] if len(filled) == 1 else [filled[0], filled[-1]]
        for region in sample:
            page_text = region.text
            self.read_crop(image, region)
            if not _texts_match(page_text, region.text):
                for item in regions:
                    self.read_crop(image, item)
                self.warnings.append(
                    f"VLM перепутал номера рамок ({pass_name}), текст дочитан по кропам"
                )
                return

    def read_crop(self, image: Image.Image, region: TextRegion) -> str:
        """Прочитать текст кропа и записать его в регион."""
        width, height = image.size
        x, y, box_w, box_h = region.bbox
        pad = 8
        crop = image.crop((
            max(0, x - pad),
            max(0, y - pad),
            min(width, x + box_w + pad),
            min(height, y + box_h + pad),
        ))
        try:
            payload = self.client.chat_json(
                prompt=(
                    "Read the text in this crop. Return the original text and its type "
                    "(dialogue, narration, title, sfx, sign, noise). "
                    "If there is no text, use an empty string and type noise."
                ),
                schema=CROP_SCHEMA,
                schema_name="crop_ocr",
                images=[crop],
                max_tokens=512,
            )
        except Exception as exc:
            logger.warning(f"Crop reread failed for region {region.id}: {exc}")
            return region.text
        region.text = str(payload.get("text") or "").strip()
        block_type = str(payload.get("type") or "").strip().lower()
        if block_type in BLOCK_TYPES:
            region.block_type = block_type
        elif not region.text:
            region.block_type = "noise"
        return region.text

    def _reread_empty(self, image: Image.Image, regions: list[TextRegion]) -> None:
        for region in regions:
            if region.text.strip() or region.confidence < self.reread_confidence:
                continue
            self.read_crop(image, region)
