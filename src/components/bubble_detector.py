"""Детектор баллонов и текста: ogkalu RT-DETR-v2 (ONNX)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from src.utils.logger import logger
from src.utils.paths import resolve_model

CLASS_NAMES = {0: "bubble", 1: "text_bubble", 2: "text_free"}
INPUT_SIZE = 640


@dataclass
class Detection:
    """Один бокс детектора. bbox — x, y, w, h."""

    bbox: tuple[int, int, int, int]
    class_id: int
    class_name: str
    confidence: float


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def merge_duplicates(detections: list[Detection], iou_threshold: float = 0.5) -> list[Detection]:
    """NMS внутри одного класса: из пары дублей остаётся более уверенный."""
    kept: list[Detection] = []
    ordered = sorted(detections, key=lambda item: item.confidence, reverse=True)
    for detection in ordered:
        if any(
            detection.class_id == other.class_id and _iou(detection.bbox, other.bbox) >= iou_threshold
            for other in kept
        ):
            continue
        kept.append(detection)
    return kept


class BubbleDetector:
    """ONNX-инференс RT-DETR. orig_target_sizes передаётся как [w, h]."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        conf: float = 0.3,
        providers: list[str] | None = None,
    ):
        self.model_path = Path(model_path) if model_path else self._default_model()
        self.conf = conf
        self.providers = providers or ["CPUExecutionProvider"]
        self._session = None

    @staticmethod
    def _default_model() -> Path:
        for name in ("ogkalu-detector.onnx", "ogkalu-detector-v4-s_int8.onnx"):
            path = resolve_model(name)
            if path.exists():
                return path
        return resolve_model("ogkalu-detector.onnx")

    def _load(self):
        if self._session is not None:
            return self._session
        import onnxruntime as ort

        if not self.model_path.exists():
            raise FileNotFoundError(f"Не найден детектор: {self.model_path}")
        logger.info(f"Loading bubble detector: {self.model_path.name}")
        self._session = ort.InferenceSession(str(self.model_path), providers=self.providers)
        return self._session

    def detect(self, image: Image.Image) -> list[Detection]:
        """Найти баллоны и текст. Координаты в пикселях исходного изображения."""
        session = self._load()
        rgb = np.array(image.convert("RGB"))
        height, width = rgb.shape[:2]
        resized = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
        blob = resized.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[None]

        labels, boxes, scores = session.run(
            None,
            {
                "images": blob,
                "orig_target_sizes": np.array([[width, height]], dtype=np.int64),
            },
        )

        detections: list[Detection] = []
        for label, box, score in zip(labels[0], boxes[0], scores[0]):
            confidence = float(score)
            if confidence < self.conf:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.tolist())
            x1 = max(0, min(width - 1, int(round(x1))))
            y1 = max(0, min(height - 1, int(round(y1))))
            x2 = max(0, min(width, int(round(x2))))
            y2 = max(0, min(height, int(round(y2))))
            box_w = x2 - x1
            box_h = y2 - y1
            if box_w < 4 or box_h < 4:
                continue
            class_id = int(label)
            detections.append(Detection(
                bbox=(x1, y1, box_w, box_h),
                class_id=class_id,
                class_name=CLASS_NAMES.get(class_id, f"class_{class_id}"),
                confidence=confidence,
            ))

        merged = merge_duplicates(detections)
        logger.info(f"Detector: {len(merged)} boxes (raw {len(detections)})")
        return merged
