"""Оффлайн-OCR: RapidOCR (PP-OCRv5), слова раскладываются по регионам детектора."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from PIL import Image

from src.models import TextRegion
from src.utils.logger import logger

# Короткие подписи действий — содержательный текст комикса, а не вывески.
_ACTIONS = frozenset({"startle", "shake", "whisper", "squeeze", "pull", "kiss",
                      "glance", "jiggle", "shiver", "tremble", "nod", "gulp",
                      "nudge", "poke", "pat", "blush", "giggle", "sniff", "sob"})
# Ник и адрес остаются вывеской, даже если строка обрывается многоточием.
_HANDLE_RE = re.compile(r"@[\w.-]+")
_URL_RE = re.compile(r"(https?://|www\.|\b[\w.-]+\.(com|net|org|ru|io|me|tv|gg)(/|\b))", re.IGNORECASE)


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


def _same_reading_line(word: OcrWord, line: list[OcrWord]) -> bool:
    """Слово в строке, если пересекает соседа хотя бы на половину меньшей высоты."""
    for other in line:
        top = max(word.bbox[1], other.bbox[1])
        bottom = min(word.bbox[1] + word.bbox[3], other.bbox[1] + other.bbox[3])
        overlap = bottom - top
        smaller = min(word.bbox[3], other.bbox[3])
        if smaller > 0 and overlap >= smaller * 0.5:
            return True
    return False


def _reading_lines(words: list[OcrWord], direction: str = "ltr") -> list[OcrWord]:
    """Строки по вертикальному пересечению, слова внутри строки слева направо.

    Деление ``y // высота_слова`` путает высокий нижний знак и низкий верхний.
    Вертикальный столбец не склеивается: у соседей сверху и снизу нет пересечения.
    Для RTL меняется только направление внутри строки.
    """
    pending = sorted(words, key=lambda word: (word.center[1], word.bbox[0]))
    lines: list[list[OcrWord]] = []
    for word in pending:
        for line in reversed(lines):
            if _same_reading_line(word, line):
                line.append(word)
                break
        else:
            lines.append([word])
    lines.sort(key=lambda line: sum(item.bbox[1] for item in line) / len(line))
    reverse = direction == "rtl"
    ordered: list[OcrWord] = []
    for line in lines:
        line.sort(key=lambda item: item.bbox[0], reverse=reverse)
        ordered.extend(line)
    return ordered


class RapidOcr:
    """Фолбэк, когда VLM недоступна. Тип блока оценивается геометрией."""

    def __init__(self, min_confidence: float = 0.3, intra_op_threads: int = 0):
        self.min_confidence = min_confidence
        self.intra_op_threads = max(0, int(intra_op_threads))
        self._engine = None

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR
        from src.utils.resources import ocr_params

        params = ocr_params()
        if self.intra_op_threads:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = self.intra_op_threads
        self._engine = RapidOCR(params=params)
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
        words = _reading_lines(self._words(crop), "ltr")
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
        buckets: dict[int, list[OcrWord]] = {region.id: [] for region in regions}
        unassigned: list[OcrWord] = []
        for word in words:
            containers = []
            for region in regions:
                target = region.bubble_bbox or region.bbox
                if not _point_in_box(word.center, target):
                    continue
                containers.append((target[2] * target[3], region.id))
            if not containers:
                unassigned.append(word)
                continue
            containers.sort(key=lambda item: (item[0], item[1]))
            buckets[containers[0][1]].append(word)
        for region in regions:
            ordered = _reading_lines(buckets.get(region.id, []), direction)
            region.text = " ".join(word.text for word in ordered).strip()
            # Короткая реплика может пропасть при OCR всей страницы. Повторяем
            # только пустой речевой кроп, не трогая исключения и найденный текст.
            if not region.text and region.bubble_bbox is not None and not region.skip:
                self.read_crop(image, region)
            self._guess_type(region)
        # OCR видит и надписи, которым детектор не дал область. Сохраняем
        # уверенные звуки отдельно; вывески, подписи автора и шум не добавляем.
        from src.components.text_regions import overlap_ratio

        regions = list(regions)
        recovered: list[TextRegion] = []
        for word in unassigned:
            if word.confidence < .55 or "@" in word.text or "_" in word.text:
                continue
            letters = sum(char.isalpha() for char in word.text)
            if letters < 2 or letters < len(word.text.strip()) * .5:
                continue
            if any(overlap_ratio(word.bbox, r.bbox) > .8 or
                   (word.text.casefold() == r.text.casefold() and
                    overlap_ratio(word.bbox, r.bbox) > .4) for r in regions):
                continue
            candidate = TextRegion(
                max((r.id for r in regions), default=0) + 1, word.bbox,
                text=word.text, confidence=word.confidence, class_name="text_free",
                order=len(regions),
            )
            self._guess_type(candidate)
            if candidate.block_type == "sfx":
                regions.append(candidate)
                recovered.append(candidate)
        # У наклонного многострочного звука OCR иногда читает только одну
        # букву строки с дефисом. Самостоятельной целью такой фрагмент не
        # становится; присоединяем его лишь к пересекающемуся найденному звуку.
        from src.components.text_regions import union_box

        for word in unassigned:
            if (word.confidence < .5 or "-" not in word.text or
                    sum(char.isalpha() for char in word.text) != 1):
                continue
            for candidate in recovered:
                overlap = overlap_ratio(word.bbox, candidate.bbox)
                if not .2 < overlap < .8:
                    continue
                if word.bbox[2] > candidate.bbox[2] * 1.5 or word.bbox[3] > candidate.bbox[3] * 1.5:
                    continue
                candidate.bbox = union_box([candidate.bbox, word.bbox])
                candidate.text = word.text + " " + candidate.text
                break
        logger.info(f"RapidOCR: {len(words)} words, direction {direction}")
        return direction, regions

    @staticmethod
    def _guess_type(region: TextRegion) -> None:
        """Эвристика типа без VLM: баллон — всегда dialogue, короткие вывески — sign.

        Междометие и короткое действие не вывеска: одно слово с ! ? или
        многоточием — звук, более длинная такая строка — повествование.
        """
        text = region.text.strip()
        letters = [char for char in text if char.isalpha()]
        shout = bool(letters) and text.upper() == text and len(text) <= 24
        if region.bubble_bbox is not None:
            region.block_type = "dialogue"
            return
        from src.components.sfx_dict import lookup

        action = text.strip(" .!?,;:-…").casefold() in _ACTIONS
        if shout or action or lookup(text) is not None:
            region.block_type = "sfx"
            return
        if _HANDLE_RE.search(text) or _URL_RE.search(text):
            region.block_type = "sign"
            return
        words = text.split()
        if text.endswith(("!", "?", "…", "...")):
            region.block_type = "sfx" if len(words) == 1 else "narration"
            return
        short_label = bool(letters) and (
            len(text) <= 12 or (len(words) <= 3 and len(text) <= 24)
        )
        region.block_type = "sign" if short_label else "narration"
