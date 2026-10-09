"""Пайплайн v2: детекция, OCR страницы, перевод, очистка, вёрстка."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

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


def _sfx_on(config: Config) -> bool:
    """Звукоподражания включены: режим replace или старый флаг translate_sfx."""
    if str(getattr(config, "sfx_mode", "") or "").strip().lower() == "replace":
        return True
    return bool(getattr(config, "translate_sfx", False))


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


def _scale_regions(regions: list[TextRegion], factor: float) -> None:
    """Масштаб рамок и кеглей регионов на месте."""
    if factor == 1.0 or not regions:
        return
    for region in regions:
        region.bbox = _scale_box(region.bbox, factor)
        if region.bubble_bbox is not None:
            region.bubble_bbox = _scale_box(region.bubble_bbox, factor)
        size = int(getattr(region.style, "font_size", 0) or 0)
        if size > 0:
            region.style.font_size = max(1, int(round(size * factor)))
        override = int(getattr(region.style, "font_size_override", 0) or 0)
        if override > 0:
            region.style.font_size_override = max(1, int(round(override * factor)))


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
        self.typesetter = typesetter or Typesetter(
            min_font_size=max(10, self.config.min_font_size),
            max_font_size=max(128, self.config.max_font_size),
            lang=self.config.target_lang,
            stroke_ratio=self.config.text_stroke_ratio,
            margin_ratio=self.config.text_margin,
        )
        self.ocr_name = ""
        self.translator_name = ""
        self._llm_down = False
        self._step_timings: dict[str, float] = {}

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
        )
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        stages.append("typeset")
        timings["typeset"] = self._step_timings.get("typeset", 0.0)
        if layout_scale != 1.0:
            rendered = rendered.resize(image.size, Image.Resampling.LANCZOS)
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
        detections = filter_detections(self._detect(work), work.size)
        direction_hint = self._geometric_order()
        regions = build_regions(detections, reading_order=direction_hint)
        regions = refine_document_regions(np.array(work), regions, reading_order=direction_hint)
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
            timings["ocr"] = time.perf_counter() - started
            stages.append("ocr")
            if debug:
                self._save_marked(work, regions, debug)

            report(45, "Перевод", "translate")
            started = time.perf_counter()
            self.typesetter.lang = target_lang
            regions = self._translate(work, regions, source_lang, target_lang, warnings)
            timings["translate"] = time.perf_counter() - started
            stages.append("translate")

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
        if not _skip_layout_scale:
            work, layout_scale = _layout_scale(
                image, int(getattr(self.config, "layout_long_side", 2000) or 0)
            )
            if layout_scale != 1.0:
                _scale_regions(regions, layout_scale)
                if strokes:
                    strokes = [
                        MaskStroke(
                            mode=stroke.mode,
                            radius=max(1, int(round(stroke.radius * layout_scale))),
                            points=[
                                (int(round(x * layout_scale)), int(round(y * layout_scale)))
                                for x, y in stroke.points
                            ],
                        )
                        for stroke in strokes
                    ]

        report(65, "Маска букв", "segment")
        started = time.perf_counter()
        drawable = self._drawable(regions)
        sfx_regions = [region for region in drawable if region.block_type == "sfx"]
        other_regions = [region for region in drawable if region.block_type != "sfx"]
        inks: dict[int, np.ndarray] = {}
        mask_other = segment_regions(work, other_regions)
        mask_sfx = segment_regions(work, sfx_regions, capture_ink=inks)
        mask = np.maximum(mask_other, mask_sfx)
        self._merge_captured_sfx(work, sfx_regions, inks)
        mask = apply_strokes(mask, strokes or [])
        self._step_timings["segment"] = time.perf_counter() - started
        if debug:
            Image.fromarray(mask).save(debug / "03_mask.png")

        report(75, "Очистка текста", "inpaint")
        started = time.perf_counter()
        if not np.any(mask):
            cleaned = work
        else:
            sfx_part = np.where((mask > 0) & (mask_sfx > 0), np.uint8(255), np.uint8(0))
            other_part = np.where((mask > 0) & (mask_sfx == 0), np.uint8(255), np.uint8(0))
            if not np.any(sfx_part):
                cleaned = self._inpaint(work, mask, warnings)
            else:
                cleaned = work
                if np.any(other_part):
                    cleaned = self._inpaint(cleaned, other_part, warnings)
                cleaned = self._inpaint(cleaned, sfx_part, warnings, allow_flat_fill=False)
        self._step_timings["inpaint"] = time.perf_counter() - started
        if layout_scale != 1.0:
            cleaned = cleaned.resize(image.size, Image.Resampling.LANCZOS)
            mask = np.array(
                Image.fromarray(mask).resize(image.size, Image.Resampling.NEAREST)
            )
            _scale_regions(regions, 1.0 / layout_scale)
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
    ) -> tuple[Image.Image, list[int]]:
        """Вёрстка с сокращением. Второй результат — id регионов, которые не влезли."""
        report = _bind_report(progress_callback, cancel_check)
        if warnings is None:
            warnings = []
        work = cleaned
        layout_scale = 1.0
        if not _skip_layout_scale:
            work, layout_scale = _layout_scale(
                cleaned, int(getattr(self.config, "layout_long_side", 2000) or 0)
            )
            if layout_scale != 1.0:
                _scale_regions(regions, layout_scale)
        report(85, "Вёрстка", "typeset")
        self.typesetter.lang = target_lang
        started = time.perf_counter()
        rendered, overflow = self._typeset(work, regions, target_lang, warnings)
        self._step_timings["typeset"] = time.perf_counter() - started
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        if layout_scale != 1.0:
            rendered = rendered.resize(cleaned.size, Image.Resampling.LANCZOS)
            _scale_regions(regions, 1.0 / layout_scale)
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
        path = Path(regions_json)
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = Path(payload["source_path"])
        if not source.exists():
            neighbour = path.parent / source.name
            source = neighbour if neighbour.exists() else source
        image = _load_image(source)
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
            {},
        )
        if debug:
            rendered.save(debug / "05_result.jpg", quality=90)
            self._dump(result, debug)
        return result

    def recognize_region(self, image: Image.Image, region: TextRegion) -> TextRegion:
        """Распознать один регион: VLM, если сервер жив, иначе RapidOCR."""
        warnings: list[str] = []
        self._prepare_ocr(warnings)
        if isinstance(self.ocr, VlmOcr) and self.ocr.client.available():
            self.ocr.read_crop(image, region)
            return region
        if not isinstance(self.ocr, RapidOcr):
            self._llm_down = True
            self.ocr = RapidOcr(min_confidence=self.config.min_confidence)
            self.ocr_name = "rapid"
        self.ocr.read_crop(image, region)
        return region

    def retranslate_region(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        region_id: int,
        source_lang: str,
        target_lang: str,
    ) -> TextRegion:
        """Перевести один регион текущим переводчиком, с контекстом страницы."""
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
        for region in regions:
            if region.id == int(region_id):
                return region
        raise ValueError(f"Регион {region_id} не найден")

    def shorten_region(self, region: TextRegion, target_lang: str) -> TextRegion:
        """Сократить перевод региона примерно до 70 % длины."""
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

    def _detect(self, image: Image.Image):
        if self.detector is None:
            self.detector = BubbleDetector(conf=self.config.detector_conf)
        return self.detector.detect(image)

    def _client(self) -> LlmClient:
        return LlmClient(
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
            thinking=self.config.llm_thinking,
            timeout=self.config.llm_timeout,
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
            logger.warning(f"OCR failed, RapidOCR fallback: {exc}")
            warnings.append(f"OCR переключён на RapidOCR: {exc}")
            self.ocr = RapidOcr(min_confidence=self.config.min_confidence)
            self.ocr_name = "rapid"
            self._llm_down = True
            return self.ocr.recognize(image, regions, reading_order=self.config.reading_order)
        warnings.extend(getattr(self.ocr, "warnings", []) or [])
        return direction, recognized

    def _prepare_ocr(self, warnings: list[str]) -> None:
        if self.ocr is not None:
            if not self.ocr_name:
                self.ocr_name = "custom"
            return
        if self.config.ocr_backend == "rapid" or self._llm_down:
            self.ocr = RapidOcr(min_confidence=self.config.min_confidence)
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
        self.ocr = RapidOcr(min_confidence=self.config.min_confidence)
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
            if region.edited or region.block_type != "sfx":
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
            self.inpainter = LamaInpainter(
                device=self.config.device,
                force_opencv=self.config.inpainter_backend == "opencv",
            )
        try:
            return self.inpainter.inpaint(image, mask, allow_flat_fill=allow_flat_fill)
        except Exception as exc:
            logger.warning(f"Inpaint failed: {exc}")
            warnings.append(f"Очистка не удалась: {exc}")
            return image

    def _typeset(
        self,
        image: Image.Image,
        regions,
        target_lang: str,
        warnings: list[str],
    ) -> tuple[Image.Image, list[int]]:
        rendered = image
        overflow: list[int] = []
        for attempt in range(3):
            force = attempt == 2
            rendered, overflow = self.typesetter.render(image, regions, force=force)
            if not overflow or force:
                break
            for region in regions:
                if region.id not in overflow:
                    continue
                limit = max(8, int(len(region.translation) * 0.7))
                try:
                    region.translation = self.translator.shorten(
                        region.translation,
                        target_lang=target_lang,
                        max_chars=limit,
                        speaker_gender=region.speaker_gender,
                        original=region.text,
                    )
                except Exception as exc:
                    warnings.append(f"Не удалось сократить регион {region.id}: {exc}")
                    rendered, overflow = self.typesetter.render(image, regions, force=True)
                    return rendered, overflow
        if overflow:
            warnings.append(f"Текст не влез полностью: {overflow}")
        return rendered, overflow
