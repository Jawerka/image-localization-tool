"""Пайплайн v2: детекция, OCR страницы, перевод, очистка, вёрстка."""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw

from src.config import Config
from src.errors import CriticalPipelineError, PipelineCancelled
from src.models import MaskStroke, PageResult, TextRegion, should_translate
from src.components.bubble_detector import BubbleDetector
from src.components.text_regions import build_regions, filter_detections, refine_document_regions
from src.components.text_segmenter import apply_strokes, segment_regions
from src.components.vlm_ocr import VlmOcr, draw_marked_page
from src.components.rapid_ocr import RapidOcr
from src.components.llm_translator import ArgosBlockTranslator, LlmTranslator, load_glossary
from src.components.sfx_style import estimate_style
from src.components.lama_inpainter import LamaInpainter
from src.components.font_catalog import assign_stylized_fonts
from src.components.adaptive_text import prepare_regions, adaptive_masks
from src.components.text_discovery import discover_missing_text
from src.components.typesetter import Typesetter
from src.utils.llm_client import LlmClient
from src.utils.logger import logger

ProgressCallback = Callable[..., None]
CancelCheck = Callable[[], bool]


def _bind_report(
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
):
    """Статус, отмена и совместимость со старым callback (progress, status)."""

    def report(progress: int, status: str, stage: str = "") -> None:
        if cancel_check and cancel_check():
            raise PipelineCancelled(status or "Отменено", stage=stage)
        if progress_callback is not None:
            try:
                progress_callback(progress, status, stage)
            except TypeError:
                progress_callback(progress, status)
        logger.info(status)

    return report


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise PipelineCancelled()


def _sfx_on(config: Config) -> bool:
    """Звукоподражания включены: режим replace или старый флаг translate_sfx."""
    if str(getattr(config, "sfx_mode", "") or "").strip().lower() == "replace":
        return True
    return bool(getattr(config, "translate_sfx", False))


def _detector_mode(config: Config) -> str:
    """ogkalu, ctd, both или auto. Неизвестное значение — только первый детектор.

    auto разрешается в analyze: оба детектора только при живой языковой модели.
    """
    mode = str(getattr(config, "detector_mode", "ogkalu") or "ogkalu").strip().lower()
    if mode not in ("ogkalu", "ctd", "both", "auto"):
        return "ogkalu"
    return mode


def _merge_sfx_style(region: TextRegion, image_rgb: np.ndarray, ink: np.ndarray) -> None:
    """Стартовые цвета SFX. Угол и изгиб не копируем: первая вёрстка прямая.

    Цвета — только при stroke_mode auto. Перевод и font_id не трогаем.
    """
    estimated = estimate_style(image_rgb, ink)
    style = region.style
    if str(style.stroke_mode or "auto").strip().lower() != "auto":
        return
    fill = estimated.get("fill_rgb")
    stroke = estimated.get("stroke_rgb")
    if fill is not None:
        style.fill_rgb = tuple(int(channel) for channel in list(fill)[:3])
    if stroke is not None:
        style.stroke_rgb = tuple(int(channel) for channel in list(stroke)[:3])
    if estimated.get("stroke_width") is not None:
        style.stroke_width = float(estimated["stroke_width"])


def _load_image(path: str | Path) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
    except FileNotFoundError as exc:
        raise CriticalPipelineError(str(exc), stage="load") from exc
    except Exception as exc:
        raise CriticalPipelineError(f"Cannot load image: {exc}", stage="load") from exc
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _layout_scale(image: Image.Image, target_long: int) -> tuple[Image.Image, float]:
    """Поднятие мелкой страницы до ``target_long`` по длинной стороне. Иначе scale=1."""
    target = int(target_long or 0)
    width, height = image.size
    long_side = max(width, height)
    if target <= 0 or long_side <= 0 or long_side >= target:
        return image, 1.0
    factor = float(target) / float(long_side)
    size = (max(1, int(round(width * factor))), max(1, int(round(height * factor))))
    return image.resize(size, Image.Resampling.LANCZOS), factor


def _scale_box(box, factor: float):
    if not box or factor == 1.0:
        return box
    return tuple(int(round(float(value) * factor)) for value in box)


def _scale_float(value, factor: float):
    """Дробная пиксельная величина. 0.0 остаётся 0.0, а не целым нулём."""
    return round(float(value) * factor, 6)


def _scale_point_component(value, factor: float):
    """Координата точки: целое значение остаётся целым после округления."""
    scaled = round(float(value) * factor, 6)
    return int(scaled) if scaled.is_integer() else scaled


def _scale_points(points, factor: float):
    if not isinstance(points, list) or factor == 1.0:
        return points
    scaled = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return points
        scaled.append([
            _scale_point_component(point[0], factor),
            _scale_point_component(point[1], factor),
        ])
    return scaled


def _scale_regions(regions: list[TextRegion], factor: float) -> None:
    """Масштаб всех пиксельных величин региона на месте.

    Рамка, позиция текста, интервалы, обводка и точки warp живут в одной
    системе координат. ``layout_snapshot`` не трогаем: он уже в координатах
    превью и при увеличении страницы стал бы невалидным.
    """
    if factor == 1.0 or not regions:
        return
    for region in regions:
        region.bbox = _scale_box(region.bbox, factor)
        if region.bubble_bbox is not None:
            region.bubble_bbox = _scale_box(region.bubble_bbox, factor)
        if region.text_position is not None:
            region.text_position = (
                _scale_float(region.text_position[0], factor),
                _scale_float(region.text_position[1], factor),
            )
        style = region.style
        size = int(getattr(style, "font_size", 0) or 0)
        if size > 0:
            style.font_size = max(1, int(round(size * factor)))
        override = int(getattr(style, "font_size_override", 0) or 0)
        if override > 0:
            style.font_size_override = max(1, int(round(override * factor)))
        line_height = int(getattr(style, "line_height", 0) or 0)
        if line_height > 0:
            style.line_height = max(1, int(round(line_height * factor)))
        style.stroke_width = _scale_float(style.stroke_width, factor)
        style.letter_spacing = _scale_float(style.letter_spacing, factor)
        style.line_spacing = _scale_float(style.line_spacing, factor)
        warp = style.warp
        if isinstance(warp, dict):
            warp["quad"] = _scale_points(warp.get("quad"), factor)
            warp["mesh"] = _scale_points(warp.get("mesh"), factor)
        if region.auto_layout:
            meta = region.auto_layout
            if meta.get("ink_bbox"):
                meta["ink_bbox"] = list(_scale_box(meta["ink_bbox"], factor))
            if meta.get("source_bbox"):
                meta["source_bbox"] = list(_scale_box(meta["source_bbox"], factor))
            if meta.get("contour"):
                meta["contour"] = _scale_points(meta["contour"], factor)
            if meta.get("source_lines"):
                meta["source_lines"] = [[round(float(v)*factor, 6) for v in row]
                                        for row in meta["source_lines"]]
            for key in ("outline_px", "mask_pad_px"):
                if key in meta:
                    meta[key] = round(float(meta[key]) * factor, 6)


def _working_regions(regions: list[TextRegion], factor: float) -> list[TextRegion]:
    """Копия регионов в рабочем разрешении. Исходные объекты не меняются."""
    if factor == 1.0 or not regions:
        return regions
    working = copy.deepcopy(regions)
    _scale_regions(working, factor)
    return working


def _commit_regions(regions: list[TextRegion], working: list[TextRegion], factor: float) -> None:
    """Вернуть рабочую копию в исходный масштаб и записать её в те же объекты.

    Геометрия, которую задал пользователь, берётся из объекта до старта:
    обратное округление не должно сдвигать рамку, позицию и точки warp.
    """
    if factor == 1.0 or working is regions:
        return
    _scale_regions(working, 1.0 / factor)
    for original, updated in zip(regions, working):
        updated.bbox = original.bbox
        updated.bubble_bbox = original.bubble_bbox
        updated.text_position = original.text_position
        updated.layout_snapshot = original.layout_snapshot
        warp = updated.style.warp
        source_warp = original.style.warp or {}
        if isinstance(warp, dict):
            warp["quad"] = copy.deepcopy(source_warp.get("quad"))
            warp["mesh"] = copy.deepcopy(source_warp.get("mesh"))
        original.__dict__.clear()
        original.__dict__.update(updated.__dict__)


def _composite_changes(source: Image.Image, work: Image.Image, produced: Image.Image) -> Image.Image:
    """Вернуть исходник, заменив только пиксели, изменившиеся в рабочем разрешении.

    Маска изменений уменьшается максимумом и расширяется на 3 пикселя: ядро
    LANCZOS при уменьшении задевает соседние пиксели, их тоже берём из
    пересчитанной картинки. Вне этой области пиксели исходника сохраняются точно.
    """
    if produced.size == source.size:
        return produced
    changed = np.any(
        np.asarray(produced.convert("RGB")) != np.asarray(work.convert("RGB")),
        axis=2,
    )
    if not np.any(changed):
        return source
    src_h, src_w = changed.shape
    dst_w, dst_h = source.size
    ys = np.minimum((np.arange(src_h) * dst_h) // src_h, dst_h - 1)
    xs = np.minimum((np.arange(src_w) * dst_w) // src_w, dst_w - 1)
    small = np.zeros((dst_h, dst_w), dtype=np.uint8)
    np.maximum.at(small, (ys[:, None], xs[None, :]), changed.astype(np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    small = cv2.dilate(small, kernel, iterations=1)
    reduced = np.asarray(produced.resize(source.size, Image.Resampling.LANCZOS).convert("RGB"))
    base = np.array(source.convert("RGB"))
    use = small > 0
    base[use] = reduced[use]
    return Image.fromarray(base, "RGB")


def _has_frozen_layout(regions) -> bool:
    """Есть ли на странице snapshot: тогда рендер идёт в нативном разрешении."""
    return any(
        isinstance(getattr(region, "layout_snapshot", None), dict)
        for region in regions or ()
    )


def _draw_detections(image: Image.Image, detections) -> Image.Image:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    colors = {"bubble": (30, 90, 220), "text_bubble": (220, 0, 0), "text_free": (0, 150, 60)}
    for detection in detections:
        x, y, w, h = detection.bbox
        draw.rectangle((x, y, x + w, y + h), outline=colors.get(detection.class_name, (200, 160, 0)), width=2)
    return canvas


class PagePipeline:
    """Сквозной перевод страницы с поэтапными фолбэками."""

    def __init__(
        self,
        config: Config | None = None,
        detector: BubbleDetector | None = None,
        ocr=None,
        translator=None,
        inpainter: LamaInpainter | None = None,
        typesetter: Typesetter | None = None,
    ):
        self.config = config or Config()
        self.detector = detector
        self.ocr = ocr
        self.translator = translator
        self.inpainter = inpainter
        min_font = int(self.config.min_font_size)
        max_font = max(min_font, int(self.config.max_font_size))
        self.typesetter = typesetter or Typesetter(
            min_font_size=min_font,
            max_font_size=max_font,
            lang=self.config.target_lang,
            stroke_ratio=self.config.text_stroke_ratio,
            margin_ratio=self.config.text_margin,
            adaptive_text=self.config.adaptive_text,
            font_scale=self.config.text_scale,
        )
        self.ocr_name = ""
        self.translator_name = ""
        self._shared_client = None
        self._llm_down = False
        self._step_timings: dict[str, float] = {}
        self.ctd_detector = None
        self.ctd_seg = None
        self._ctd_unavailable = False

    def process(
        self,
        image_path: str,
        source_lang: str = "en",
        target_lang: str = "ru",
        progress_callback: ProgressCallback | None = None,
        debug_dir: str | Path | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> PageResult:
        report = _bind_report(progress_callback, cancel_check)
        debug = Path(debug_dir) if debug_dir else None
        if debug:
            debug.mkdir(parents=True, exist_ok=True)

        report(0, "Загрузка изображения", "load")
        started = time.perf_counter()
        image = _load_image(image_path)
        load_time = time.perf_counter() - started
        work, layout_scale = _layout_scale(image, int(getattr(self.config, "layout_long_side", 2000) or 0))

        analyzed = self.analyze(
            work,
            str(image_path),
            source_lang,
            target_lang,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            debug_dir=debug,
            _skip_layout_scale=True,
            _native_pixel_scale=layout_scale,
        )
        warnings = analyzed.warnings
        stages = ["load", *analyzed.stages_completed]
        timings = {"load": load_time, **analyzed.timings}
        regions = analyzed.regions
        direction = analyzed.reading_direction

        if not regions:
            report(100, "Текст не найден")
            return self._result(image_path, image, regions, direction, warnings, stages, timings)

        drawable = self._drawable(regions)
        report(60, f"К вёрстке: {len(drawable)}")
        if not drawable:
            if layout_scale != 1.0:
                _scale_regions(regions, 1.0 / layout_scale)
            result = self._result(image_path, image, regions, direction, warnings, stages, timings)
            self._dump(result, debug)
            return result

        _mask, cleaned = self.clean(
            work,
            regions,
            warnings=warnings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            debug_dir=debug,
            _skip_layout_scale=True,
        )
        stages.extend(["segment", "inpaint"])
        timings["segment"] = self._step_timings.get("segment", 0.0)
        timings["inpaint"] = self._step_timings.get("inpaint", 0.0)

        rendered, overflow = self.typeset_image(
            cleaned,
            drawable,
            target_lang,
            warnings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            _skip_layout_scale=True,
            _native_pixel_scale=layout_scale,
        )
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        stages.append("typeset")
        timings["typeset"] = self._step_timings.get("typeset", 0.0)
        if layout_scale != 1.0:
            rendered = _composite_changes(image, work, rendered)
            _scale_regions(regions, 1.0 / layout_scale)
        report(100, "Готово")

        result = self._result(image_path, rendered, regions, direction, warnings, stages, timings)
        self._dump(result, debug)
        if debug:
            rendered.save(debug / "05_result.jpg", quality=90)
        return result

    def analyze(
        self,
        image: Image.Image,
        source_path: str,
        source_lang: str,
        target_lang: str,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        debug_dir: str | Path | None = None,
        _skip_layout_scale: bool = False,
        _native_pixel_scale: float = 1.0,
    ) -> PageResult:
        """Детекция, OCR и перевод. Картинка результата — исходная страница."""
        report = _bind_report(progress_callback, cancel_check)
        warnings: list[str] = []
        stages: list[str] = []
        timings: dict[str, float] = {}
        debug = Path(debug_dir) if debug_dir else None
        if debug:
            debug.mkdir(parents=True, exist_ok=True)

        work = image
        layout_scale = 1.0
        if not _skip_layout_scale:
            work, layout_scale = _layout_scale(
                image, int(getattr(self.config, "layout_long_side", 2000) or 0)
            )

        report(8, "Детекция баллонов и текста", "detect")
        started = time.perf_counter()
        requested = _detector_mode(self.config)
        mode = requested
        # В auto второй детектор молчит, если файла нет: режим и так необязательный.
        quiet_missing = False
        if requested == "auto":
            self._prepare_ocr(warnings)
            mode = "both" if self.ocr_name == "vlm" else "ogkalu"
            quiet_missing = True
        if mode == "ctd":
            detections = []
        else:
            detections = filter_detections(self._detect(work), work.size)
        direction_hint = self._geometric_order()
        regions = build_regions(detections, reading_order=direction_hint)
        regions = refine_document_regions(np.array(work), regions, reading_order=direction_hint)
        if mode in ("ctd", "both") and _sfx_on(self.config):
            regions = self._add_ctd_regions(
                work, regions, warnings, replace=mode == "ctd", quiet=quiet_missing,
            )
        timings["detect"] = time.perf_counter() - started
        stages.append("detect")
        if debug:
            _draw_detections(work, detections).save(debug / "01_detect.jpg", quality=90)
        report(20, f"Регионов: {len(regions)}", "detect")

        direction = "ltr"
        if regions:
            report(25, "Распознавание текста", "ocr")
            started = time.perf_counter()
            direction, regions = self._recognize(work, regions, warnings)
            regions = self._keep_ctd_reads(work, regions)
            timings["ocr"] = time.perf_counter() - started
            stages.append("ocr")
            if debug:
                self._save_marked(work, regions, debug)

        if getattr(self.config, "discover_missing_text", True) and not self._llm_down:
            # Не открываем сеть при явно выбранном RapidOCR или подставном OCR в тестах.
            self._prepare_ocr(warnings)
            if self.ocr_name == "vlm":
                report(38, "Поиск пропущенных надписей", "ocr")
                discovery_started = time.perf_counter()
                try:
                    client = self._shared_client or self._client()
                    extras = discover_missing_text(work, regions, client, self.config.vlm_max_side)
                    regions.extend(extras)
                    if extras:
                        from src.components.text_regions import assign_reading_order
                        assign_reading_order(regions, direction)
                except Exception as exc:
                    warnings.append(f"Дополнительный поиск текста не удался: {exc}")
                timings['ocr'] = timings.get('ocr', 0.) + time.perf_counter() - discovery_started
                if 'ocr' not in stages:
                    stages.append('ocr')

        if regions:
            report(45, "Перевод", "translate")
            started = time.perf_counter()
            self.typesetter.lang = target_lang
            regions = self._translate(work, regions, source_lang, target_lang, warnings)
            untranslated = [r.id for r in regions if should_translate(r, _sfx_on(self.config)) and not r.translation.strip()]
            if untranslated:
                warnings.append(f"Не переведены регионы: {untranslated}")
            timings["translate"] = time.perf_counter() - started
            stages.append("translate")

        if getattr(self.config, "adaptive_text", True):
            prepare_regions(work, self._drawable(regions), pixel_scale=layout_scale * _native_pixel_scale)

        if layout_scale != 1.0:
            _scale_regions(regions, 1.0 / layout_scale)
        return self._result(source_path, image, regions, direction, warnings, stages, timings)

    def clean(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        strokes: list[MaskStroke] | None = None,
        warnings: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        debug_dir: str | Path | None = None,
        _skip_layout_scale: bool = False,
    ) -> tuple[np.ndarray, Image.Image]:
        """Маска переводимых регионов, штрихи и очистка. Пустая маска не идёт в inpaint."""
        report = _bind_report(progress_callback, cancel_check)
        if warnings is None:
            warnings = []
        debug = Path(debug_dir) if debug_dir else None
        if debug:
            debug.mkdir(parents=True, exist_ok=True)

        work = image
        layout_scale = 1.0
        active = regions
        if not _skip_layout_scale:
            work, layout_scale = _layout_scale(
                image, int(getattr(self.config, "layout_long_side", 2000) or 0)
            )
            if layout_scale != 1.0:
                active = _working_regions(regions, layout_scale)
                if strokes:
                    strokes = [
                        MaskStroke(
                            mode=stroke.mode,
                            radius=max(1, int(round(stroke.radius * layout_scale))),
                            points=[
                                (int(round(x * layout_scale)), int(round(y * layout_scale)))
                                for x, y in stroke.points
                            ],
                            tolerance=stroke.tolerance,
                        )
                        for stroke in strokes
                    ]

        report(65, "Маска букв", "segment")
        started = time.perf_counter()
        drawable = self._drawable(active)
        for region in drawable:
            region._retouch_preserve_background = False
        adaptive = bool(getattr(self.config, "adaptive_text", True))
        if adaptive:
            prepare_regions(work, drawable, pixel_scale=layout_scale)
        sfx_regions = [region for region in drawable if region.block_type == "sfx"]
        other_regions = [region for region in drawable if region.block_type != "sfx"]
        inks: dict[int, np.ndarray] = {}
        bubble_inset = int(getattr(self.config, "bubble_mask_inset_px", 2) or 0)
        letter_grow = max(0, int(getattr(self.config, "letter_mask_grow_px", 1) or 0))
        ordinary = [r for r in other_regions if not adaptive or not r.auto_layout or
                    (r.auto_layout.get("kind") == "bubble" and r.bubble_bbox is not None)]
        legacy_sfx = [r for r in sfx_regions if not adaptive or not r.auto_layout]
        mask_other = segment_regions(
            work, ordinary, bubble_inset_px=bubble_inset, letter_grow_px=letter_grow,
        )
        mask_sfx = segment_regions(
            work, legacy_sfx, capture_ink=inks, bubble_inset_px=bubble_inset,
            letter_grow_px=letter_grow,
        )
        if adaptive:
            mask_other, mask_sfx = adaptive_masks(
                work, drawable, mask_other, mask_sfx, grow_px=letter_grow,
            )
        if bool(getattr(self.config, "ctd_seg_clip", False)):
            from src.components.ctd_detector import clip_outlined_mask

            seg = getattr(self, "ctd_seg", None)
            if seg is not None and seg.shape[:2] != mask_sfx.shape[:2]:
                seg = cv2.resize(seg, (mask_sfx.shape[1], mask_sfx.shape[0]), interpolation=cv2.INTER_NEAREST)
            mask_sfx = clip_outlined_mask(mask_sfx, sfx_regions, seg)
        mask = np.maximum(mask_other, mask_sfx)
        self._merge_captured_sfx(work, sfx_regions, inks)
        mask = apply_strokes(mask, strokes or [], work)
        # Плашки с просвечивающим рисунком и подтверждённая обводка требуют
        # восстановления изображения, даже если узкое кольцо локально ровное.
        from src.components.retouch_ink import preserves_picture

        preserve = np.zeros_like(mask)
        work_rgb = np.asarray(work)
        for region in drawable:
            x, y, w, h = region.bbox
            xa, ya = max(0, x), max(0, y)
            xb, yb = min(work.width, x+w), min(work.height, y+h)
            if xb <= xa or yb <= ya:
                continue
            picture = (region.bubble_bbox is not None and preserves_picture(work_rgb[ya:yb, xa:xb]))
            if picture or getattr(region, '_retouch_preserve_background', False):
                pad = 34 if (region.auto_layout or {}).get('kind') == 'free' else 16
                preserve[max(0, ya-pad):min(work.height, yb+pad), max(0, xa-pad):min(work.width, xb+pad)] = 255
        self._step_timings["segment"] = time.perf_counter() - started
        if debug:
            Image.fromarray(mask).save(debug / "03_mask.png")

        report(75, "Очистка текста", "inpaint")
        started = time.perf_counter()
        if not np.any(mask):
            cleaned = work
        else:
            reconstruct = (mask_sfx > 0) | (preserve > 0)
            sfx_part = np.where((mask > 0) & reconstruct, np.uint8(255), np.uint8(0))
            other_part = np.where((mask > 0) & ~reconstruct, np.uint8(255), np.uint8(0))
            if not np.any(sfx_part):
                cleaned = self._inpaint(work, mask, warnings)
            else:
                cleaned = work
                if np.any(other_part):
                    cleaned = self._inpaint(cleaned, other_part, warnings)
                cleaned = self._inpaint(cleaned, sfx_part, warnings, allow_flat_fill=False)
        # На подтверждённом гладком фоне LaMa иногда рисует тонкую линию.
        # Медианный фильтр убирает её только внутри автоматической маски,
        # не меняя исходные границы облачка и соседний рисунок.
        smooth_regions = [r for r in drawable if getattr(r, '_retouch_smooth_background', False)
                          and not r.manual and not r.edited]
        if smooth_regions and np.any(mask):
            rgb = np.array(cleaned)
            for region in smooth_regions:
                x, y, w, h = region.bbox
                xa, ya = max(0, x-3), max(0, y-3)
                xb, yb = min(work.width, x+w+3), min(work.height, y+h+3)
                patch = rgb[ya:yb, xa:xb]
                if min(patch.shape[:2]) < 25:
                    continue
                filtered = cv2.medianBlur(patch, 25)
                selected = mask[ya:yb, xa:xb] > 0
                patch[selected] = filtered[selected]
            cleaned = Image.fromarray(rgb)
        self._step_timings["inpaint"] = time.perf_counter() - started
        if not np.any(mask):
            if layout_scale != 1.0:
                _commit_regions(regions, active, layout_scale)
            empty = np.zeros((image.height, image.width), dtype=np.uint8)
            if debug:
                image.save(debug / "04_clean.jpg", quality=90)
            return empty, image
        if layout_scale != 1.0:
            cleaned = _composite_changes(image, work, cleaned)
            mask = np.array(
                Image.fromarray(mask).resize(image.size, Image.Resampling.NEAREST)
            )
            _commit_regions(regions, active, layout_scale)
        if debug:
            cleaned.save(debug / "04_clean.jpg", quality=90)
        return mask, cleaned

    def typeset_image(
        self,
        cleaned: Image.Image,
        regions: list[TextRegion],
        target_lang: str,
        warnings: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        _skip_layout_scale: bool = False,
        incremental: dict | None = None,
        _native_pixel_scale: float = 1.0,
    ) -> tuple[Image.Image, list[int]]:
        """Вёрстка переводов. Второй результат — id регионов, которые не влезли."""
        report = _bind_report(progress_callback, cancel_check)
        if warnings is None:
            warnings = []
        work = cleaned
        layout_scale = 1.0
        # Snapshot живёт в координатах preview: масштабирование страницы
        # сдвинуло бы bbox/кегли и сделало раскладку невалидной.
        frozen = _has_frozen_layout(regions)
        active = regions
        if not _skip_layout_scale and not frozen:
            work, layout_scale = _layout_scale(
                cleaned, int(getattr(self.config, "layout_long_side", 2000) or 0)
            )
            if layout_scale != 1.0:
                active = _working_regions(regions, layout_scale)
        report(85, "Вёрстка", "typeset")
        self.typesetter.lang = target_lang
        started = time.perf_counter()
        incremental_details = None
        # Partial compose переиспользует старую растеризацию. Если прошлый
        # документ был в другом режиме масштаба, соседние регионы разойдутся.
        if incremental and frozen != _has_frozen_layout(
            incremental.get("previous_regions") or []
        ):
            incremental = None
        original_min = self.typesetter.min_font_size
        self.typesetter.min_font_size = math.ceil(self.config.min_font_size * layout_scale * _native_pixel_scale)
        try:
            if incremental and layout_scale == 1.0:
                assign_stylized_fonts(
                    active,
                    enabled=bool(getattr(self.config, "auto_stylized_fonts", True)),
                    adaptive=bool(getattr(self.config, "adaptive_text", True)),
                )
                rendered, overflow, incremental_details = self.typesetter.render_incremental(
                    work,
                    active,
                    incremental["previous_regions"],
                    incremental["previous_result"],
                    incremental["previous_bounds"],
                    incremental["changed_region_ids"],
                    force=True,
                )
                warnings[:] = [item for item in warnings if not item.startswith("Текст не влез полностью:")]
                if overflow:
                    warnings.append(f"Текст не влез полностью: {overflow}")
            else:
                rendered, overflow = self._typeset(work, active, target_lang, warnings)
        finally:
            self.typesetter.min_font_size = original_min
        self._last_typeset_details = incremental_details or {"mode": "full"}
        self._step_timings["typeset"] = time.perf_counter() - started
        overflow_ids = set(overflow)
        for region in active:
            region.overflow = region.id in overflow_ids
        if layout_scale != 1.0:
            rendered = _composite_changes(cleaned, work, rendered)
            _commit_regions(regions, active, layout_scale)
            self.typesetter._last_region_bounds = {
                region_id: (
                    max(0, int(math.floor(bounds[0] / layout_scale))),
                    max(0, int(math.floor(bounds[1] / layout_scale))),
                    min(cleaned.width, int(math.ceil(bounds[2] / layout_scale))),
                    min(cleaned.height, int(math.ceil(bounds[3] / layout_scale))),
                ) if bounds is not None else None
                for region_id, bounds in self.typesetter._last_region_bounds.items()
            }
        return rendered, overflow

    def retypeset(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        target_lang: str | None = None,
        source_path: str = "",
        reading_direction: str = "ltr",
        warnings: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> PageResult:
        """Повторная вёрстка уже очищенной картинки."""
        lang = target_lang or self.config.target_lang
        if warnings is None:
            warnings = []
        rendered, overflow = self.typeset_image(
            image,
            self._drawable(regions),
            lang,
            warnings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        return self._result(
            source_path,
            rendered,
            regions,
            reading_direction,
            warnings,
            ["typeset"],
            {"typeset": self._step_timings.get("typeset", 0.0)},
        )

    def rerender(self, regions_json: str | Path, debug_dir: str | Path | None = None) -> PageResult:
        """Повторная очистка и вёрстка после правки regions.json."""
        started = time.perf_counter()
        path = Path(regions_json)
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = Path(payload["source_path"])
        if not source.exists():
            neighbour = path.parent / source.name
            source = neighbour if neighbour.exists() else source
        image = _load_image(source)
        load_time = time.perf_counter() - started
        regions = [TextRegion.from_dict(item) for item in payload.get("regions") or []]
        strokes = [MaskStroke.from_dict(item) for item in payload.get("strokes") or []]
        warnings = list(payload.get("warnings") or [])
        debug = Path(debug_dir) if debug_dir else None
        _mask, cleaned = self.clean(image, regions, strokes=strokes, warnings=warnings, debug_dir=debug)
        rendered, overflow = self.typeset_image(
            cleaned,
            self._drawable(regions),
            self.config.target_lang,
            warnings,
        )
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        result = self._result(
            str(source),
            rendered,
            regions,
            str(payload.get("reading_direction") or "ltr"),
            warnings,
            ["load", "segment", "inpaint", "typeset"],
            {
                "load": load_time,
                "segment": self._step_timings.get("segment", 0.0),
                "inpaint": self._step_timings.get("inpaint", 0.0),
                "typeset": self._step_timings.get("typeset", 0.0),
            },
        )
        if debug:
            rendered.save(debug / "05_result.jpg", quality=90)
            self._dump(result, debug)
        return result

    def recognize_region(
        self,
        image: Image.Image,
        region: TextRegion,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> TextRegion:
        """Распознать один регион: VLM, если сервер жив, иначе RapidOCR."""
        _check_cancel(cancel_check)
        warnings: list[str] = []
        self._prepare_ocr(warnings)
        if isinstance(self.ocr, VlmOcr) and self.ocr.client.available():
            self.ocr.read_crop(image, region)
            _check_cancel(cancel_check)
            return region
        if not isinstance(self.ocr, RapidOcr):
            self._llm_down = True
            self.ocr = RapidOcr(min_confidence=self.config.min_confidence,
                                intra_op_threads=self.config.ort_intra_op_threads)
            self.ocr_name = "rapid"
        self.ocr.read_crop(image, region)
        _check_cancel(cancel_check)
        return region

    def retranslate_region(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        region_id: int,
        source_lang: str,
        target_lang: str,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> TextRegion:
        """Перевести один регион текущим переводчиком, с контекстом страницы."""
        _check_cancel(cancel_check)
        warnings: list[str] = []
        glossary = load_glossary(self.config.glossary_path)
        self._prepare_translator(warnings)
        ids = {int(region_id)}
        try:
            self.translator.translate_subset(
                image,
                regions,
                ids,
                source_lang,
                target_lang,
                glossary=glossary,
                translate_sfx=_sfx_on(self.config),
            )
            warnings.extend(getattr(self.translator, "warnings", []) or [])
        except Exception as exc:
            _check_cancel(cancel_check)
            logger.warning(f"Translator failed, Argos fallback: {exc}")
            self.translator = ArgosBlockTranslator()
            self.translator_name = "argos"
            self.translator.translate_subset(
                image,
                regions,
                ids,
                source_lang,
                target_lang,
                glossary=glossary,
                translate_sfx=_sfx_on(self.config),
            )
            warnings.extend(getattr(self.translator, "warnings", []) or [])
        _check_cancel(cancel_check)
        for region in regions:
            if region.id == int(region_id):
                return region
        raise ValueError(f"Регион {region_id} не найден")

    def shorten_region(
        self,
        region: TextRegion,
        target_lang: str,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> TextRegion:
        """Сократить перевод региона примерно до 70 % длины."""
        _check_cancel(cancel_check)
        warnings: list[str] = []
        self._prepare_translator(warnings)
        limit = max(8, int(len(region.translation) * 0.7))
        region.translation = self.translator.shorten(
            region.translation,
            target_lang=target_lang,
            max_chars=limit,
            speaker_gender=region.speaker_gender,
            original=region.text,
        )
        _check_cancel(cancel_check)
        return region

    def _result(self, source, image, regions, direction, warnings, stages, timings) -> PageResult:
        return PageResult(
            source_path=str(source),
            output_image=image,
            regions=regions,
            reading_direction=direction,
            warnings=warnings,
            stages_completed=stages,
            timings={key: round(value, 3) for key, value in timings.items()},
            ocr_engine=self.ocr_name,
            translator_engine=self.translator_name,
        )

    def _dump(self, result: PageResult, debug: Path | None) -> None:
        if debug is None:
            return
        (debug / "regions.json").write_text(
            json.dumps(result.regions_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _drawable(self, regions: list[TextRegion]) -> list[TextRegion]:
        return [
            region for region in regions
            if region.translation.strip() and should_translate(region, _sfx_on(self.config))
        ]

    def _geometric_order(self) -> str:
        if self.config.reading_order in ("ltr", "rtl"):
            return self.config.reading_order
        return "ltr"

    def _add_ctd_regions(self, image, regions, warnings: list[str], replace: bool, quiet: bool = False):
        """Предложения второго детектора. В режиме ctd они заменяют боксы первого.

        В режиме both остаются только боксы вне уже найденных областей.
        Такие боксы помечаются from_ctd и после OCR фильтруются.
        quiet глушит предупреждение об отсутствующем файле.
        """
        page = self._read_ctd(image, warnings, quiet=quiet)
        if page is None:
            return regions
        self.ctd_seg = page.seg
        direction = self._geometric_order()
        if replace:
            built = build_regions(page.boxes, reading_order=direction)
            return refine_document_regions(np.array(image), built, reading_order=direction)
        from src.components.text_regions import overlap_ratio

        occupied = []
        for region in regions:
            occupied.append(region.bbox)
            if region.bubble_bbox is not None:
                occupied.append(region.bubble_bbox)
        extras = []
        next_id = max((region.id for region in regions), default=0)
        for box in page.boxes:
            if any(
                overlap_ratio(box.bbox, item) > 0.3 or overlap_ratio(item, box.bbox) > 0.3
                for item in occupied
            ):
                continue
            next_id += 1
            region = TextRegion(
                id=next_id,
                bbox=box.bbox,
                class_name="text_free",
                confidence=box.confidence,
                block_type="narration",
            )
            region.from_ctd = True
            extras.append(region)
            occupied.append(box.bbox)
        if not extras:
            return regions
        from src.components.text_regions import assign_reading_order

        merged = list(regions) + extras
        assign_reading_order(merged, "rtl" if direction == "rtl" else "ltr")
        return merged

    def _read_ctd(self, image, warnings: list[str], quiet: bool = False):
        if self._ctd_unavailable:
            return None
        try:
            if self.ctd_detector is None:
                from src.components.ctd_detector import ComicTextDetector
                from src.utils.paths import resolve_model

                threads = int(getattr(self.config, "ort_intra_op_threads", 0) or 0) or 4
                self.ctd_detector = ComicTextDetector(
                    model_path=resolve_model(
                        "comictextdetector.pt.onnx", self.config.models_dir or None,
                    ),
                    conf=float(getattr(self.config, "ctd_conf", 0.4) or 0.4),
                    intra_op_threads=threads,
                )
            return self.ctd_detector.detect(image)
        except FileNotFoundError as exc:
            self._ctd_unavailable = True
            if not quiet:
                warnings.append("Детектор звуков не найден, страница обрабатывается без него")
            logger.warning(str(exc))
            return None
        except Exception as exc:
            self._ctd_unavailable = True
            warnings.append(f"Детектор звуков пропущен: {exc}")
            logger.warning(f"CTD failed: {exc}")
            return None

    def _keep_ctd_reads(self, image, regions):
        """Без языковой модели предложение остаётся, только если это звук из букв."""
        if not any(getattr(region, "from_ctd", False) for region in regions):
            return regions
        kept = []
        for region in regions:
            if not getattr(region, "from_ctd", False):
                kept.append(region)
                continue
            reader = self.ocr
            if reader is None or not hasattr(reader, "read_crop"):
                continue
            try:
                reader.read_crop(image, region)
            except Exception as exc:
                logger.warning(f"CTD crop read failed: {exc}")
                continue
            if self.ocr_name == "vlm":
                letters = sum(char.isalpha() for char in region.text or "")
                if letters >= 2 and region.block_type not in ("noise", "sign", ""):
                    kept.append(region)
                continue
            RapidOcr._guess_type(region)
            letters = sum(char.isalpha() for char in region.text or "")
            if letters >= 2 and region.block_type == "sfx":
                kept.append(region)
        return kept

    def _detect(self, image: Image.Image):
        if self.detector is None:
            from src.utils.paths import resolve_model

            self.detector = BubbleDetector(
                conf=self.config.detector_conf,
                intra_op_threads=self.config.ort_intra_op_threads,
                model_path=resolve_model("ogkalu-detector-v4-s_int8.onnx", self.config.models_dir or None),
            )
        return self.detector.detect(image)

    def _client(self) -> LlmClient:
        return LlmClient(
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
            thinking=self.config.llm_thinking,
            timeout=self.config.llm_timeout,
            api_key=getattr(self.config, "llm_api_key", ""),
        )

    def _save_marked(self, image, regions, debug: Path) -> None:
        """Картинки проходов OCR: ровно то, что уходит в VLM."""
        bubbles = [region for region in regions if region.bubble_bbox is not None]
        free = [region for region in regions if region.bubble_bbox is None]
        side = self.config.vlm_max_side
        if bubbles:
            draw_marked_page(image, bubbles, max_side=side).save(debug / "02_marked_bubbles.jpg", quality=90)
        if free:
            draw_marked_page(image, free, max_side=side).save(debug / "02_marked_free.jpg", quality=90)

    def _recognize(self, image, regions, warnings: list[str]):
        self._prepare_ocr(warnings)
        try:
            direction, recognized = self.ocr.recognize(
                image, regions, reading_order=self.config.reading_order,
            )
        except Exception as exc:
            if isinstance(self.ocr, RapidOcr):
                raise
            logger.warning(f"OCR failed, RapidOCR fallback: {exc}")
            fallback = RapidOcr(min_confidence=self.config.min_confidence,
                                intra_op_threads=self.config.ort_intra_op_threads)
            try:
                direction, recognized = fallback.recognize(
                    image, regions, reading_order=self.config.reading_order,
                )
            except Exception as fallback_exc:
                # Битый ответ LLM не переводит процесс на RapidOCR навсегда.
                # Если фолбэк сам не поднялся, следующая страница снова идёт в VLM.
                logger.warning(f"RapidOCR fallback failed: {fallback_exc}")
                raise exc from fallback_exc
            warnings.append(f"OCR переключён на RapidOCR: {exc}")
            self.ocr = fallback
            self.ocr_name = "rapid"
            self._llm_down = True
            return direction, recognized
        warnings.extend(getattr(self.ocr, "warnings", []) or [])
        return direction, recognized

    def _prepare_ocr(self, warnings: list[str]) -> None:
        if self.ocr is not None:
            if not self.ocr_name:
                self.ocr_name = "custom"
            return
        if self.config.ocr_backend == "rapid" or self._llm_down:
            self.ocr = RapidOcr(min_confidence=self.config.min_confidence,
                                intra_op_threads=self.config.ort_intra_op_threads)
            self.ocr_name = "rapid"
            return
        client = self._client()
        if client.available():
            self.ocr = VlmOcr(client, max_side=self.config.vlm_max_side)
            self.ocr_name = "vlm"
            self._shared_client = client
            return
        self._llm_down = True
        warnings.append("Сервер LLM недоступен, используется RapidOCR + Argos")
        self.ocr = RapidOcr(min_confidence=self.config.min_confidence,
                            intra_op_threads=self.config.ort_intra_op_threads)
        self.ocr_name = "rapid"

    def _translate(self, image, regions, source_lang, target_lang, warnings: list[str]):
        glossary = load_glossary(self.config.glossary_path)
        self._prepare_translator(warnings)
        try:
            translated = self.translator.translate(
                image,
                regions,
                source_lang,
                target_lang,
                glossary=glossary,
                translate_sfx=_sfx_on(self.config),
            )
            warnings.extend(getattr(self.translator, "warnings", []) or [])
            return translated
        except Exception as exc:
            logger.warning(f"Translator failed, Argos fallback: {exc}")
            warnings.append(f"Перевод переключён на Argos: {exc}")
            self.translator = ArgosBlockTranslator()
            self.translator_name = "argos"
            translated = self.translator.translate(
                image,
                regions,
                source_lang,
                target_lang,
                glossary=glossary,
                translate_sfx=_sfx_on(self.config),
            )
            warnings.extend(getattr(self.translator, "warnings", []) or [])
            return translated

    def _prepare_translator(self, warnings: list[str]) -> None:
        if self.translator is not None:
            if not self.translator_name:
                self.translator_name = "custom"
            return
        if self.config.translator_backend == "argos" or self._llm_down:
            self.translator = ArgosBlockTranslator()
            self.translator_name = "argos"
            if self._llm_down and self.config.translator_backend == "llm":
                if not any("Argos" in item for item in warnings):
                    warnings.append("Сервер LLM недоступен, используется RapidOCR + Argos")
            return
        client = getattr(self, "_shared_client", None) or self._client()
        if client.available():
            self.translator = LlmTranslator(client)
            self.translator_name = "llm"
            return
        self._llm_down = True
        warnings.append("Сервер LLM недоступен, используется RapidOCR + Argos")
        self.translator = ArgosBlockTranslator()
        self.translator_name = "argos"

    def _merge_captured_sfx(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        inks: dict[int, np.ndarray],
    ) -> None:
        """Оценка стиля SFX по чернилам. Правленый регион не затираем."""
        if not inks or not _sfx_on(self.config):
            return
        rgb = np.array(image.convert("RGB"))
        for region in regions:
            if region.edited or region.manual or region.layout_snapshot or region.block_type != "sfx":
                continue
            ink = inks.get(region.id)
            if ink is None or not np.any(ink):
                continue
            _merge_sfx_style(region, rgb, ink)

    def _inpaint(
        self,
        image: Image.Image,
        mask: np.ndarray,
        warnings: list[str],
        allow_flat_fill: bool = True,
    ) -> Image.Image:
        if self.inpainter is None:
            from src.utils.paths import resolve_model

            self.inpainter = LamaInpainter(
                model_path=resolve_model(
                    "anime-manga-big-lama.pt", self.config.models_dir or None),
                device=self.config.device,
                force_opencv=self.config.inpainter_backend == "opencv",
            )
        try:
            cleaned = self.inpainter.inpaint(image, mask, allow_flat_fill=allow_flat_fill)
        except Exception as exc:
            logger.warning(f"Inpaint failed: {exc}")
            warnings.append(f"Очистка не удалась: {exc}")
            return image
        notes = [str(note) for note in (getattr(self.inpainter, "last_warnings", None) or []) if note]
        if not notes:
            # Успешная LaMa/заливка — убрать устаревший баннер про OpenCV/shm.
            stale = ("очистка переключена на opencv", "lama недоступна", "shm.dll")
            warnings[:] = [
                item for item in warnings
                if not any(marker in str(item).casefold() for marker in stale)
            ]
        for text in notes:
            if text not in warnings:
                warnings.append(text)
        return cleaned

    def _typeset(
        self,
        image: Image.Image,
        regions,
        target_lang: str,
        warnings: list[str],
    ) -> tuple[Image.Image, list[int]]:
        assign_stylized_fonts(
            regions,
            enabled=bool(getattr(self.config, "auto_stylized_fonts", True)),
            adaptive=bool(getattr(self.config, "adaptive_text", True)),
        )
        rendered, overflow = self.typesetter.render(image, regions, force=True)
        # Повторная вёрстка заменяет результат своей проверки, а не накапливает его.
        warnings[:] = [item for item in warnings if not item.startswith("Текст не влез полностью:")]
        if overflow:
            warnings.append(f"Текст не влез полностью: {overflow}")
        return rendered, overflow
