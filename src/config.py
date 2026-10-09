"""Конфигурация приложения."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Config:
    """Конфигурация пайплайна v2 и CLI."""

    # Язык перевода по умолчанию
    target_lang: str = "ru"

    # Минимальная уверенность OCR (0.0 - 1.0), для RapidOCR
    min_confidence: float = 0.5

    # Минимальный размер шрифта
    min_font_size: int = 10

    # Максимальный размер шрифта
    max_font_size: int = 128

    # Путь к конфигу файлу
    _config_path: Path = field(default_factory=lambda: Path("config.json"), repr=False)

    # Пайплайн v2
    source_lang: str = "en"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = ""
    llm_thinking: bool = False
    llm_timeout: int = 300
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
    translate_sfx: bool = False
    # skip | replace. replace включает перевод звукоподражаний.
    sfx_mode: str = "skip"
    device: str = "auto"
    glossary_path: str = ""
    detector_conf: float = 0.3
    # Ореол цвета фона вокруг перевода. 0 — без ореола.
    text_stroke_ratio: float = 0.08
    # Доля меньшей стороны баллона, которую не занимает текст.
    text_margin: float = 0.08
    # Длинная сторона для разметки мелких страниц. 0 — без апскейла.
    layout_long_side: int = 2000

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
            has_sfx_mode = "sfx_mode" in data
            valid_fields = {k: v for k, v in data.items()
                          if k in cls.__dataclass_fields__}
            config = cls(**valid_fields)
            _apply_sfx_mode(config, data, has_sfx_mode)
            return config
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Could not load config: {e}")
            return cls()

    def save(self, path: str | Path | None = None) -> None:
        """Сохранить конфигурацию в файл."""
        config_path = Path(path) if path else self._config_path

        # Исключаем служебные поля
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _apply_sfx_mode(config: Config, data: dict, has_sfx_mode: bool) -> None:
    """Новый ``sfx_mode`` побеждает. Старый ``translate_sfx`` без ключа — это replace."""
    mode = str(config.sfx_mode or "skip").strip().lower()
    if mode not in ("skip", "replace"):
        mode = "skip"
    if not has_sfx_mode and data.get("translate_sfx") is True:
        mode = "replace"
    config.sfx_mode = mode
    if has_sfx_mode or mode == "replace":
        config.translate_sfx = mode == "replace"
