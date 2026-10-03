"""OCR страницы через VLM: пронумерованные рамки и дочитывание пустых боксов."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from src.models import TextRegion
from src.utils.llm_client import LlmClient
from src.utils.logger import logger

BLOCK_TYPES = ("dialogue", "narration", "title", "sfx", "sign", "noise")

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


def draw_marked_page(image: Image.Image, regions: list[TextRegion]) -> Image.Image:
    """Копия страницы с красными рамками и номерами регионов."""
    marked = image.convert("RGB").copy()
    draw = ImageDraw.Draw(marked)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for region in regions:
        x, y, w, h = region.bbox
        draw.rectangle((x, y, x + w, y + h), outline=(220, 0, 0), width=2)
        label = str(region.id)
        tx, ty = x + 2, max(0, y - 16)
        bbox = draw.textbbox((tx, ty), label, font=font)
        draw.rectangle(bbox, fill=(255, 255, 255))
        draw.text((tx, ty), label, fill=(220, 0, 0), font=font)
    return marked


def _prompt(regions: list[TextRegion], reading_order: str) -> str:
    hint = ""
    if reading_order in ("ltr", "rtl"):
        hint = f" The page reading direction is {reading_order}."
    lines = "\n".join(f"{region.id}: box at {region.bbox}" for region in regions)
    return (
        "You are reading a comic or document page. Red numbered boxes mark text regions. "
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


def _apply_order(regions: list[TextRegion], order: list) -> None:
    positions = {}
    for index, raw_id in enumerate(order):
        try:
            positions[int(raw_id)] = index
        except (TypeError, ValueError):
            continue
    if not positions:
        return
    for region in regions:
        if region.id in positions:
            region.order = positions[region.id]
    regions.sort(key=lambda item: item.order)


class VlmOcr:
    """Один запрос на страницу. Пустые уверенные боксы дочитываются по кропу."""

    def __init__(self, client: LlmClient, reread_confidence: float = 0.5):
        self.client = client
        self.reread_confidence = reread_confidence

    def recognize(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        reading_order: str = "auto",
    ) -> tuple[str, list[TextRegion]]:
        if not regions:
            return "ltr", regions

        marked = draw_marked_page(image, regions)
        payload = self.client.chat_json(
            prompt=_prompt(regions, reading_order),
            schema=OCR_SCHEMA,
            schema_name="page_ocr",
            images=[marked],
        )
        by_id = {region.id: region for region in regions}
        for block in payload.get("blocks") or []:
            try:
                region_id = int(block.get("id"))
            except (TypeError, ValueError):
                continue
            region = by_id.get(region_id)
            if region is None:
                continue
            region.text = str(block.get("text") or "").strip()
            block_type = str(block.get("type") or "").strip().lower()
            if block_type in BLOCK_TYPES:
                region.block_type = block_type

        direction = str(payload.get("reading_direction") or "ltr").lower()
        if direction not in ("ltr", "rtl"):
            direction = "rtl" if reading_order == "rtl" else "ltr"
        _apply_order(regions, payload.get("order") or [])
        self._reread_empty(image, regions)
        logger.info(f"VLM OCR: {sum(1 for r in regions if r.text)} non-empty blocks, {direction}")
        return direction, regions

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
