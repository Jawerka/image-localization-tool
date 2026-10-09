"""Очистка текста: заливка ровного фона, иначе LaMa-manga, иначе OpenCV."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from src.utils.logger import logger
from src.utils.paths import resolve_model


def resolve_device(preference: str = "auto") -> str:
    """auto → cuda, если torch его видит, иначе cpu."""
    if preference and preference != "auto":
        return preference
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _ceil_mod(value: int, modulo: int = 8) -> int:
    if value % modulo == 0:
        return value
    return (value // modulo + 1) * modulo


# Окно длиннее этого идёт кусками. Короткий штрих остаётся одним проходом.
_LAMA_LIMIT = 1024
_TILE = 768
_TILE_OVERLAP = 192


def _window_bounds(
    component: np.ndarray,
    shape: tuple[int, int],
    pad: int,
) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(component > 0)
    if ys.size == 0:
        return None
    height, width = shape
    y0 = max(0, int(ys.min()) - pad)
    x0 = max(0, int(xs.min()) - pad)
    y1 = min(height, int(ys.max()) + pad + 1)
    x1 = min(width, int(xs.max()) + pad + 1)
    return y0, x0, y1, x1


def _tile_starts(length: int, tile: int, step: int) -> list[int]:
    """Начала кропов, последний дотягивается до края."""
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, step))
    last = length - tile
    if starts[-1] != last:
        starts.append(last)
    return starts


def _feather(height: int, width: int, fade: int) -> np.ndarray:
    """Вес кропа: к краю меньше, чтобы перекрытие не давало шва."""
    fade = max(1, min(fade, height // 2, width // 2))
    ramp = np.linspace(0.05, 1.0, fade, dtype=np.float32)
    wy = np.ones(height, dtype=np.float32)
    wx = np.ones(width, dtype=np.float32)
    wy[:fade] = ramp
    wy[-fade:] = ramp[::-1]
    wx[:fade] = ramp
    wx[-fade:] = ramp[::-1]
    return wy[:, None] * wx[None, :]


class LamaInpainter:
    """Заливка однородного баллона или LaMa. Большое окно режется без уменьшения."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        device: str = "auto",
        force_opencv: bool = False,
        uniform_std: float = 14.0,
    ):
        self.model_path = Path(model_path) if model_path else resolve_model("anime-manga-big-lama.pt")
        self.device = resolve_device(device)
        self.force_opencv = force_opencv
        self.uniform_std = uniform_std
        self._model = None

    def inpaint(
        self,
        image: Image.Image,
        mask: np.ndarray,
        allow_flat_fill: bool = True,
    ) -> Image.Image:
        """Удалить пиксели маски. Сначала заливки, потом один проход LaMa.

        ``allow_flat_fill=False`` пропускает однотонную заливку. Дальше тот же
        путь: LaMa, либо OpenCV, если включён ``force_opencv``.
        """
        rgb = np.array(image.convert("RGB"))
        binary = (mask > 0).astype(np.uint8) * 255
        if binary.shape[:2] != rgb.shape[:2] or not np.any(binary):
            return Image.fromarray(rgb)

        num, labels = cv2.connectedComponents(binary)
        result = rgb.copy()
        pending: list[np.ndarray] = []
        for label_id in range(1, num):
            component = np.where(labels == label_id, 255, 0).astype(np.uint8)
            if allow_flat_fill and self._fill_if_uniform(result, component, binary):
                continue
            pending.append(component)
        if not pending:
            return Image.fromarray(result)

        lama_mask = np.zeros_like(binary)
        for component in pending:
            lama_mask = np.maximum(lama_mask, component)
        dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        lama_mask = cv2.dilate(lama_mask, dilate, iterations=1)

        for component in pending:
            if self.force_opencv:
                result = self._opencv_window(result, component, lama_mask)
                continue
            try:
                result = self._lama_crop(result, component, lama_mask)
            except Exception as exc:
                logger.warning(f"LaMa fallback to OpenCV: {exc}")
                result = self._opencv_window(result, component, lama_mask)
        return Image.fromarray(result)

    def _fill_if_uniform(
        self,
        image: np.ndarray,
        component: np.ndarray,
        full_mask: np.ndarray,
    ) -> bool:
        """Залить компоненту, если фон кольца однотонный (чернила соседа не в счёт)."""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        ring = (cv2.dilate(component, kernel) > 0) & (full_mask == 0)
        pixels = image[ring].astype(np.float32)
        if pixels.shape[0] < 12:
            return False
        median = np.median(pixels, axis=0)
        distances = np.linalg.norm(pixels - median, axis=1)
        # Высококонтрастные «чернила» соседа не входят в оценку фона.
        background = distances < 40
        bg_pixels = pixels[background]
        if bg_pixels.shape[0] < 12:
            return False
        median = np.median(bg_pixels, axis=0)
        inliers = np.linalg.norm(bg_pixels - median, axis=1) < 30
        if float(inliers.mean()) < 0.85 or not np.any(inliers):
            return False
        if float(bg_pixels[inliers].std(axis=0).mean()) > self.uniform_std:
            return False
        color = np.clip(np.round(median), 0, 255).astype(np.uint8)
        image[component > 0] = color
        self._clear_halo(image, component, full_mask, color)
        return True

    @staticmethod
    def _clear_halo(
        image: np.ndarray,
        component: np.ndarray,
        full_mask: np.ndarray,
        color: np.ndarray,
    ) -> None:
        """Полоса 3 px: близкие к заливке пиксели перекрасить, контур не трогать."""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        band = (cv2.dilate(component, kernel) > 0) & (component == 0) & (full_mask == 0)
        if not np.any(band):
            return
        pixels = image[band].astype(np.float32)
        close = np.linalg.norm(pixels - color.astype(np.float32), axis=1) < 60
        if not np.any(close):
            return
        updated = pixels.copy()
        updated[close] = color.astype(np.float32)
        image[band] = np.clip(np.round(updated), 0, 255).astype(np.uint8)

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise FileNotFoundError(f"Нет модели LaMa: {self.model_path}")
        import torch

        logger.info(f"Loading LaMa on {self.device}: {self.model_path.name}")
        model = torch.jit.load(str(self.model_path), map_location=self.device)
        model.eval()
        self._model = model
        return model

    def _lama_forward(self, crop: np.ndarray, crop_mask: np.ndarray) -> np.ndarray:
        """Один вызов модели без уменьшения кадра."""
        import torch

        out_h = _ceil_mod(crop.shape[0])
        out_w = _ceil_mod(crop.shape[1])
        padded_img = np.pad(
            crop,
            ((0, out_h - crop.shape[0]), (0, out_w - crop.shape[1]), (0, 0)),
            mode="symmetric",
        )
        padded_mask = np.pad(
            crop_mask,
            ((0, out_h - crop_mask.shape[0]), (0, out_w - crop_mask.shape[1])),
            mode="constant",
        )
        image_t = torch.from_numpy(padded_img.transpose(2, 0, 1).astype(np.float32) / 255.0)
        mask_t = torch.from_numpy((padded_mask > 127).astype(np.float32))
        image_t = image_t.unsqueeze(0).to(self.device)
        mask_t = mask_t.unsqueeze(0).unsqueeze(0).to(self.device)

        model = self._load_model()
        with torch.inference_mode():
            predicted = model(image_t, mask_t)
        if isinstance(predicted, (tuple, list)):
            predicted = predicted[0]
        predicted = predicted[0].detach().float().cpu().permute(1, 2, 0).numpy()
        predicted = np.clip(predicted * 255.0, 0, 255).astype(np.uint8)
        return predicted[: crop.shape[0], : crop.shape[1]]

    def _lama_tiles(
        self,
        crop: np.ndarray,
        crop_mask: np.ndarray,
        component_crop: np.ndarray,
    ) -> np.ndarray:
        """Кропы не длиннее ``_TILE``. Перекрытие смешивается, в дыру пишется только компонента."""
        color = np.zeros_like(crop, dtype=np.float32)
        weight_sum = np.zeros(crop.shape[:2], dtype=np.float32)
        step = _TILE - _TILE_OVERLAP
        for y0 in _tile_starts(crop.shape[0], _TILE, step):
            for x0 in _tile_starts(crop.shape[1], _TILE, step):
                y1 = min(crop.shape[0], y0 + _TILE)
                x1 = min(crop.shape[1], x0 + _TILE)
                if not np.any(component_crop[y0:y1, x0:x1]):
                    continue
                predicted = self._lama_forward(crop[y0:y1, x0:x1], crop_mask[y0:y1, x0:x1])
                weight = _feather(y1 - y0, x1 - x0, _TILE_OVERLAP // 2)
                hole = component_crop[y0:y1, x0:x1] > 0
                color[y0:y1, x0:x1][hole] += predicted[hole] * weight[hole, None]
                weight_sum[y0:y1, x0:x1][hole] += weight[hole]
        painted = crop.copy()
        hole = (component_crop > 0) & (weight_sum > 0)
        painted[hole] = np.clip(np.round(color[hole] / weight_sum[hole, None]), 0, 255).astype(np.uint8)
        return painted

    def _lama_crop(
        self,
        image: np.ndarray,
        component: np.ndarray,
        lama_mask: np.ndarray,
    ) -> np.ndarray:
        bounds = _window_bounds(component, image.shape[:2], pad=128)
        if bounds is None:
            return image
        y0, x0, y1, x1 = bounds
        crop = image[y0:y1, x0:x1]
        crop_mask = lama_mask[y0:y1, x0:x1]
        if max(crop.shape[0], crop.shape[1]) <= _LAMA_LIMIT:
            predicted = self._lama_forward(crop, crop_mask)
        else:
            predicted = self._lama_tiles(crop, crop_mask, component[y0:y1, x0:x1])
        return self._paste_component(image, component, predicted, y0, x0)

    def _opencv_window(
        self,
        image: np.ndarray,
        component: np.ndarray,
        lama_mask: np.ndarray,
    ) -> np.ndarray:
        """OpenCV на той же маске окна, что ушла бы в LaMa."""
        bounds = _window_bounds(component, image.shape[:2], pad=128)
        if bounds is None:
            return image
        y0, x0, y1, x1 = bounds
        crop = image[y0:y1, x0:x1]
        crop_mask = lama_mask[y0:y1, x0:x1]
        if not np.any(crop_mask):
            return image
        bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
        filled = cv2.inpaint(bgr, crop_mask, 3, cv2.INPAINT_TELEA)
        predicted = cv2.cvtColor(filled, cv2.COLOR_BGR2RGB)
        return self._paste_component(image, component, predicted, y0, x0)

    @staticmethod
    def _paste_component(
        image: np.ndarray,
        component: np.ndarray,
        predicted: np.ndarray,
        y0: int,
        x0: int,
    ) -> np.ndarray:
        """Вклеить только пиксели текущей компоненты, не соседние дыры окна."""
        y1 = y0 + predicted.shape[0]
        x1 = x0 + predicted.shape[1]
        destination = image.copy()
        patch = destination[y0:y1, x0:x1]
        hole = component[y0:y1, x0:x1] > 0
        patch[hole] = predicted[hole]
        destination[y0:y1, x0:x1] = patch
        return destination
