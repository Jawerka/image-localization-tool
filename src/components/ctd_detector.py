"""Второй детектор текста на странице комикса: comic-text-detector, ONNX.

Боксы blk уже декодированы сетью: центр, размер, объектность и два класса
текстового блока. Класса облачка нет. Карта seg возвращается в координатах
страницы и может ограничивать маску обведённого звука.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from src.components.bubble_detector import Detection, merge_duplicates
from src.utils.logger import logger
from src.utils.paths import resolve_model

INPUT_SIZE = 1024
_READ_MXCSR = None
_WRITE_MXCSR = None


def _mxcsr_ops():
    """Чтение и запись MXCSR. На этой платформе пары нет — (None, None)."""
    global _READ_MXCSR, _WRITE_MXCSR
    if _READ_MXCSR is False:
        return None, None
    if _READ_MXCSR is not None:
        return _READ_MXCSR, _WRITE_MXCSR
    if sys.platform != "win32":
        _READ_MXCSR = False
        return None, None
    try:
        # read: stmxcsr [rsp+8]; mov eax, [rsp+8]; ret
        # write: mov [rsp+8], ecx; ldmxcsr [rsp+8]; ret
        read_code = bytes((0x0F, 0xAE, 0x5C, 0x24, 0x08, 0x8B, 0x44, 0x24, 0x08, 0xC3))
        write_code = bytes((0x89, 0x4C, 0x24, 0x08, 0x0F, 0xAE, 0x54, 0x24, 0x08, 0xC3))
        kernel = ctypes.windll.kernel32
        kernel.VirtualAlloc.restype = ctypes.c_void_p
        kernel.VirtualAlloc.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32,
        ]
        addr = kernel.VirtualAlloc(None, len(read_code) + len(write_code), 0x3000, 0x40)
        if not addr:
            raise OSError("VirtualAlloc")
        ctypes.memmove(addr, read_code, len(read_code))
        ctypes.memmove(addr + len(read_code), write_code, len(write_code))
        _READ_MXCSR = ctypes.CFUNCTYPE(ctypes.c_uint32)(addr)
        _WRITE_MXCSR = ctypes.CFUNCTYPE(None, ctypes.c_uint32)(addr + len(read_code))
    except Exception:
        logger.warning("Не удалось включить FTZ/DAZ, детектор звуков может замедлиться")
        _READ_MXCSR = False
        return None, None
    return _READ_MXCSR, _WRITE_MXCSR


class _flush_denormals:
    """FTZ и DAZ только на время прогона. Иначе второй вызов детектора идёт минуту."""

    def __enter__(self):
        self._previous = None
        read, write = _mxcsr_ops()
        if read is None:
            return self
        current = int(read())
        self._previous = current
        self._write = write
        write(current | 0x8040)
        return self

    def __exit__(self, *_exc):
        if self._previous is not None:
            self._write(self._previous)
        return False


@dataclass
class CtdPage:
    """Боксы и карта сегментации в пикселях исходной страницы."""

    boxes: list[Detection]
    seg: np.ndarray


def clip_outlined_mask(
    mask: np.ndarray,
    regions,
    seg: np.ndarray | None,
    dilate_px: int = 6,
) -> np.ndarray:
    """Обрезать маску обведённого звука расширенной картой сегментации.

    Остальные пиксели маски не трогаются. Нет карты — маска прежняя.
    """
    if seg is None or mask.size == 0 or seg.shape[:2] != mask.shape[:2]:
        return mask
    radius = max(1, int(dilate_px))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    allowed = cv2.dilate((seg > 0).astype(np.uint8), kernel) > 0
    clip = np.zeros(mask.shape[:2], np.uint8)
    height, width = mask.shape[:2]
    outlined = False
    for region in regions:
        if not getattr(region, "_outline_ink", False):
            continue
        outlined = True
        x, y, box_w, box_h = (int(v) for v in region.bbox)
        pad = radius + 4
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + box_w + pad), min(height, y + box_h + pad)
        if x1 > x0 and y1 > y0:
            clip[y0:y1, x0:x1] = 255
    if not outlined:
        return mask
    drop = (mask > 0) & (clip > 0) & ~allowed
    if not np.any(drop):
        return mask
    kept = mask.copy()
    kept[drop] = 0
    return kept


class ComicTextDetector:
    """ONNX comic-text-detector. Сессия подменяется в тесте."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        conf: float = 0.4,
        providers: list[str] | None = None,
        intra_op_threads: int = 4,
        session=None,
    ):
        self.model_path = Path(model_path) if model_path else resolve_model("comictextdetector.pt.onnx")
        self.conf = float(conf)
        self.providers = providers or ["CPUExecutionProvider"]
        self.intra_op_threads = max(0, int(intra_op_threads))
        self._session = session

    def _load(self):
        if self._session is not None:
            return self._session
        import onnxruntime as ort

        if not self.model_path.exists():
            raise FileNotFoundError(f"Не найден детектор звуков: {self.model_path}")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.add_session_config_entry("session.set_denormal_as_zero", "1")
        threads = self.intra_op_threads or 4
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        logger.info(f"Loading comic text detector: {self.model_path.name}, threads {threads}")
        self._session = ort.InferenceSession(
            str(self.model_path), sess_options=options, providers=self.providers,
        )
        return self._session

    def detect(self, image: Image.Image) -> CtdPage:
        """Найти текстовые блоки и карту сегментации. Координаты — пиксели страницы."""
        session = self._load()
        rgb = np.array(image.convert("RGB"))
        height, width = rgb.shape[:2]
        blob, scale, left, top = _letterbox(rgb)
        # RapidOCR снимает FTZ/DAZ у вызывающего потока. Без этого второй прогон ~100 с.
        with _flush_denormals():
            blk, seg, _det = session.run(None, {"images": blob})
        boxes = _boxes(blk[0], scale, left, top, width, height, self.conf)
        page_seg = _unletterbox(seg[0, 0], width, height, scale, left, top)
        logger.info(f"Comic text detector: {len(boxes)} boxes")
        return CtdPage(boxes=boxes, seg=page_seg)


def _letterbox(image: np.ndarray) -> tuple[np.ndarray, float, int, int]:
    """Вписать страницу в 1024 с серыми полями. Возвращает blob, масштаб и поля."""
    height, width = image.shape[:2]
    scale = min(INPUT_SIZE / height, INPUT_SIZE / width)
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, np.uint8)
    top = (INPUT_SIZE - resized_h) // 2
    left = (INPUT_SIZE - resized_w) // 2
    canvas[top:top + resized_h, left:left + resized_w] = resized
    blob = np.ascontiguousarray(canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0)
    return blob, scale, left, top


def _boxes(
    rows: np.ndarray,
    scale: float,
    left: int,
    top: int,
    width: int,
    height: int,
    conf: float,
) -> list[Detection]:
    """Отфильтровать blk и перевести центр-размер в бокс страницы."""
    if rows.ndim != 2 or rows.shape[1] < 6 or scale <= 0:
        return []
    limit = rows[:, :4].max() if rows.size else 0.0
    pixels = rows[:, :4] * (INPUT_SIZE if limit <= 2.0 else 1.0)
    detections: list[Detection] = []
    for row, box in zip(rows, pixels):
        class_scores = row[5:]
        class_id = int(np.argmax(class_scores)) if class_scores.size else 0
        score = float(row[4]) * float(class_scores[class_id] if class_scores.size else 1.0)
        if score < conf:
            continue
        cx, cy, box_w, box_h = (float(v) for v in box)
        x1 = (cx - box_w / 2.0 - left) / scale
        y1 = (cy - box_h / 2.0 - top) / scale
        x2 = (cx + box_w / 2.0 - left) / scale
        y2 = (cy + box_h / 2.0 - top) / scale
        x1 = max(0, min(width - 1, int(round(x1))))
        y1 = max(0, min(height - 1, int(round(y1))))
        x2 = max(0, min(width, int(round(x2))))
        y2 = max(0, min(height, int(round(y2))))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        # Оба класса blk — текстовый блок, не облачко. NMS общий.
        detections.append(Detection(
            bbox=(x1, y1, x2 - x1, y2 - y1),
            class_id=0,
            class_name="text_free",
            confidence=score,
        ))
    return merge_duplicates(detections, iou_threshold=0.45)


def _unletterbox(
    seg: np.ndarray,
    width: int,
    height: int,
    scale: float,
    left: int,
    top: int,
) -> np.ndarray:
    """Вернуть карту сегментации к размеру страницы. Порог 0.3."""
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    crop = seg[top:top + resized_h, left:left + resized_w]
    if crop.size == 0:
        return np.zeros((height, width), np.uint8)
    binary = (crop >= 0.3).astype(np.uint8) * 255
    if binary.shape[1] != width or binary.shape[0] != height:
        binary = cv2.resize(binary, (width, height), interpolation=cv2.INTER_NEAREST)
    return binary
