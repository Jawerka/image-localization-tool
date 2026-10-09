"""Оффлайн-OCR: RapidOCR (PP-OCRv5), слова раскладываются по регионам детектора."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from src.models import TextRegion
from src.utils.logger import logger


@dataclass
class OcrWord:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2, y + h / 2


def _quad_to_bbox(points) -> tuple[int, int, int, int] | None:
    array = np.array(points, dtype=np.float32).reshape(-1, 2)
    if array.shape[0] < 2:
        return None
    x1, y1 = array.min(axis=0)
    x2, y2 = array.max(axis=0)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return int(x1), int(y1), int(x2 - x1), int(y2 - y1)


def _point_in_box(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y = point
    bx, by, bw, bh = box
    return bx <= x <= bx + bw and by <= y <= by + bh


class RapidOcr:
    """Фолбэк, когда VLM недоступна. Тип блока оценивается геометрией."""

    def __init__(self, min_confidence: float = 0.3):
        self.min_confidence = min_confidence
        self._engine = None

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR
        self._engine = RapidOCR()
        return self._engine

    def _words(self, image: Image.Image) -> list[OcrWord]:
        engine = self._load()
        rgb = np.array(image.convert("RGB"))
        raw = engine(rgb)
        words: list[OcrWord] = []
        if raw is None:
            return words

        boxes = getattr(raw, "boxes", None)
        texts = getattr(raw, "txts", None)
        scores = getattr(raw, "scores", None)
        if boxes is not None and texts is not None:
            score_list = list(scores) if scores is not None else [1.0] * len(texts)
            for box, text, score in zip(boxes, texts, score_list):
                self._append_word(words, box, text, score)
            return words

        rows = raw[0] if isinstance(raw, tuple) else raw
        if not rows:
            return words
        for item in rows:
            if not item or len(item) < 2:
                continue
            score = float(item[2]) if len(item) > 2 else 1.0
            self._append_word(words, item[0], item[1], score)
        return words

    def _append_word(self, words: list[OcrWord], box, text, score) -> None:
        confidence = float(score)
        if confidence < self.min_confidence:
            return
        cleaned = str(text).strip()
        if len(cleaned) < 1:
            return
        bbox = _quad_to_bbox(box)
        if bbox is None:
            return
        words.append(OcrWord(text=cleaned, bbox=bbox, confidence=confidence))

    def read_crop(self, image: Image.Image, region: TextRegion) -> str:
        """Распознать текст только внутри рамки региона."""
        width, height = image.size
        x, y, box_w, box_h = region.bbox
        pad = 8
        crop = image.crop((
            max(0, x - pad),
            max(0, y - pad),
            min(width, x + box_w + pad),
            min(height, y + box_h + pad),
        ))
        words = self._words(crop)
        words.sort(key=lambda word: (
            word.bbox[1] // max(8, word.bbox[3]),
            word.bbox[0],
        ))
        region.text = " ".join(word.text for word in words).strip()
        return region.text

    def recognize(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        reading_order: str = "auto",
    ) -> tuple[str, list[TextRegion]]:
        direction = "rtl" if reading_order == "rtl" else "ltr"
        words = self._words(image)
        for region in regions:
            target = region.bubble_bbox or region.bbox
            inside = [word for word in words if _point_in_box(word.center, target)]
            inside.sort(key=lambda word: (
                word.bbox[1] // max(8, word.bbox[3]),
                -word.bbox[0] if direction == "rtl" else word.bbox[0],
            ))
            region.text = " ".join(word.text for word in inside).strip()
            self._guess_type(region)
        logger.info(f"RapidOCR: {len(words)} words, direction {direction}")
        return direction, regions

    @staticmethod
    def _guess_type(region: TextRegion) -> None:
        """Эвристика типа без VLM: баллон — всегда dialogue, короткие вывески — sign."""
        text = region.text.strip()
        letters = [char for char in text if char.isalpha()]
        shout = bool(letters) and text.upper() == text and len(text) <= 24
        if region.bubble_bbox is not None:
            region.block_type = "dialogue"
            return
        if shout:
            region.block_type = "sfx"
            return
        words = text.split()
        short_label = bool(letters) and (
            len(text) <= 12 or (len(words) <= 3 and len(text) <= 24)
        )
        region.block_type = "sign" if short_label else "narration"
