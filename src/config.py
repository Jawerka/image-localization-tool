"""Конфигурация приложения."""

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Config:
    """Конфигурация пайплайна v2 и CLI."""

    # Язык перевода по умолчанию
    target_lang: str = "ru"

    # Вход в браузерный редактор включается владельцем явно.
    web_auth_enabled: bool = False

    # Минимальная уверенность OCR (0.0 - 1.0), для RapidOCR
    min_confidence: float = 0.5

    # Потоки ONNX Runtime внутри одной операции; 0 — автонастройка ORT.
    ort_intra_op_threads: int = 0

    # Минимальный кегль на итоговом растре; тесная область не снижает порог
    min_font_size: int = 10

    # Максимальный размер шрифта
    max_font_size: int = 128

    # Видимость слоёв рамок и маски в просмотрщике.
    viewer_show_boxes: bool = True
    viewer_show_mask: bool = True

    # Путь к конфигу файлу
    _config_path: Path = field(default_factory=lambda: Path("config.json"), repr=False)

    # Пайплайн v2
    source_lang: str = "en"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = ""
    llm_thinking: bool = False
    llm_timeout: int = 300
    # Ключ API LLM. save() его не пишет; load() читает при ручной правке файла.
    llm_api_key: str = field(default="", repr=False)
    # vlm | rapid
    ocr_backend: str = "vlm"
    # Длинная сторона страницы, которую видит VLM при OCR. Крупный скан
    # сжимается до неё, чтобы номера рамок остались читаемыми.
    vlm_max_side: int = 1536
    # llm | argos
    translator_backend: str = "llm"
    # lama | opencv
    inpainter_backend: str = "lama"
    # auto | ltr | rtl
    reading_order: str = "auto"
    translate_sfx: bool | None = None
    # skip | replace. replace включает перевод звукоподражаний.
    sfx_mode: str | None = None
    # Проба: автоподстановка CC0-шрифтов для SFX и free-текста.
    auto_stylized_fonts: bool = True
    # Оформление по исходным строкам и дополнительный поиск пропущенных надписей.
    adaptive_text: bool = True
    discover_missing_text: bool = True
    device: str = "auto"
    # Каталог внешних моделей и политика докачки компонентов.
    models_dir: str = ""
    components_dir: str = ""
    download_retries: int = 3
    download_timeout: int = 30
    download_prefetch_workers: int = 3
    download_disk_reserve_mb: int = 64
    download_cache_limit_mb: int = 4096
    # Общий предел RAM для декодированных страниц и ответов preview.
    render_cache_limit_mb: int = 256
    glossary_path: str = ""
    detector_conf: float = 0.3
    # ogkalu | ctd | both | auto. auto — второй детектор только при живой языковой модели.
    # По умолчанию основной: прогон с языковой моделью не дал прироста паре.
    detector_mode: str = "ogkalu"
    ctd_conf: float = 0.4
    # Обрезка маски обведённого звука картой второго детектора. Включается,
    # если на эталонах растёт попадание и не падает покрытие.
    ctd_seg_clip: bool = False
    # Ореол цвета фона вокруг перевода. 0 — без ореола.
    text_stroke_ratio: float = 0.08
    # Доля меньшей стороны баллона, которую не занимает текст.
    text_margin: float = 0.08
    # Масштаб автоматически подобранного текста после раскладки.
    text_scale: float = 1.1
    # Длинная сторона для разметки мелких страниц. 0 — без апскейла.
    layout_long_side: int = 2000
    # Отступ маски ретуши от контура баллона внутрь (px).
    bubble_mask_inset_px: int = 2
    # Дополнительное расширение автоматической маски букв наружу (px).
    # Силуэт баллона и ручные штрихи не растут.
    letter_mask_grow_px: int = 1

    def __post_init__(self) -> None:
        """Явный режим побеждает старый флаг; новый профиль переводит звуки."""
        try:
            self.text_scale = float(self.text_scale)
            if not math.isfinite(self.text_scale):
                raise ValueError('text_scale')
            self.text_scale = min(2.0, max(.5, self.text_scale))
        except (TypeError, ValueError):
            self.text_scale = 1.1
        if self.sfx_mode is None:
            mode = "skip" if self.translate_sfx is False else "replace"
        else:
            mode = str(self.sfx_mode).strip().lower()
            if mode not in ("skip", "replace"):
                mode = "skip"
        self.sfx_mode = mode
        self.translate_sfx = mode == "replace"
        detector_mode = str(self.detector_mode or "ogkalu").strip().lower()
        if detector_mode not in ("ogkalu", "ctd", "both", "auto"):
            detector_mode = "ogkalu"
        self.detector_mode = detector_mode
        try:
            self.ctd_conf = float(self.ctd_conf)
        except (TypeError, ValueError):
            self.ctd_conf = 0.4
        self.ctd_conf = min(0.95, max(0.05, self.ctd_conf))
        self.ctd_seg_clip = bool(self.ctd_seg_clip)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Загрузить конфигурацию из файла."""
        config_path = Path(path) if path else Path("config.json")

        if not config_path.exists():
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise TypeError("config root must be an object")
            # Фильтруем только известные поля
            valid_fields = {k: v for k, v in data.items()
                          if k in cls.__dataclass_fields__}
            # В JSON null — неверный явный режим, а не отсутствие выбора.
            if "sfx_mode" in data and data["sfx_mode"] is None:
                valid_fields["sfx_mode"] = "skip"
            config = cls(**valid_fields)
            return config
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Could not load config: {e}")
            return cls()

    def save(self, path: str | Path | None = None) -> None:
        """Сохранить конфигурацию в файл."""
        config_path = Path(path) if path else self._config_path

        # Исключаем служебные поля и секрет
        data = {
            k: v for k, v in asdict(self).items()
            if not k.startswith("_") and k != "llm_api_key"
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
