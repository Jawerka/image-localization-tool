"""Настройки настольного приложения.

Ключ API в JSON не пишется: он лежит в keyring (служба ``ImageLocalizationTool``,
имя ``llm``). Адрес LLM по умолчанию пустой — LAN-адрес из ``Config`` сюда не
подставляется.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.config import Config

SCHEMA_VERSION = 1
_KEYRING_SERVICE = "ImageLocalizationTool"
_KEYRING_USERNAME = "llm"

_THEMES = ("system", "dark", "light")
_OCR = ("vlm", "rapid")
_TRANSLATORS = ("llm", "argos")
_INPAINTERS = ("lama", "opencv")
_READING = ("auto", "ltr", "rtl")
_SFX_MODES = ("skip", "replace")
_EXPORT_FORMATS = ("png", "jpg")
_EXPORT_CONFLICTS = ("rename", "overwrite", "skip")
_BIND_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")


def get_api_key() -> str:
    """Ключ LLM из keyring. При любой ошибке хранилища — пустая строка."""
    try:
        import keyring

        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value)


def set_api_key(value: str) -> bool:
    """Записать ключ LLM. Пустая строка удаляет запись. False — keyring отказал."""
    try:
        import keyring

        if not value:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
            except Exception:
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, "")
        else:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, value)
        return True
    except Exception:
        return False


def _as_int(value, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _as_float(value, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
    return default


def _raw_text(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _choice(value, allowed: tuple[str, ...], default: str) -> str:
    text = _raw_text(value, default).lower()
    if text in allowed:
        return text
    return default


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bind_host(value) -> str:
    """Адрес прослушивания LAN. Пустое и некорректное значение — ``0.0.0.0``."""
    text = _raw_text(value, "0.0.0.0")
    if not text or any(char.isspace() for char in text):
        return "0.0.0.0"
    if any(char in text for char in "/\\?#@"):
        return "0.0.0.0"
    try:
        ipaddress.ip_address(text)
    except ValueError:
        labels = text.split(".")
        if labels and all(label.isdigit() for label in labels):
            return "0.0.0.0"
        if not _BIND_HOST.fullmatch(text) or ".." in text:
            return "0.0.0.0"
    return text


def _devices(value) -> list:
    """Список устройств: id, имя, хеш токена, время. Сырой токен сюда не попадает."""
    if not isinstance(value, list):
        return []
    result: list = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("id") or "").strip()
        token_hash = str(item.get("token_hash") or "").strip().lower()
        if not device_id or not token_hash or device_id in seen:
            continue
        seen.add(device_id)
        created_raw = item.get("created")
        if isinstance(created_raw, bool) or created_raw is None:
            created = 0.0
        else:
            try:
                created = float(created_raw)
            except (TypeError, ValueError):
                created = 0.0
        result.append(
            {
                "id": device_id,
                "name": str(item.get("name") or "").strip()[:200],
                "token_hash": token_hash,
                "created": created,
            }
        )
    return result


def _recent(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= 10:
            break
    return result


def _schema_value(data: dict) -> int | None:
    if "schema" not in data:
        return None
    try:
        return int(data["schema"])
    except (TypeError, ValueError):
        return None


def _quarantine(path: Path) -> Path:
    """Переименовать испорченный файл, не затирая уже лежащие копии ``.bad``."""
    index = 1
    while True:
        suffix = ".bad" if index == 1 else f".bad-{index}"
        candidate = Path(str(path) + suffix)
        if not candidate.exists():
            path.rename(candidate)
            return candidate
        index += 1


@dataclass
class AppSettings:
    """Пользовательские настройки. Схема 1."""

    theme: str = "system"
    ui_scale: int = 100
    source_lang: str = "en"
    target_lang: str = "ru"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_thinking: bool = False
    llm_timeout: int = 300
    ocr_backend: str = "vlm"
    translator_backend: str = "llm"
    inpainter_backend: str = "lama"
    reading_order: str = "auto"
    translate_sfx: bool = False
    sfx_mode: str = "skip"  # skip|replace
    device: str = "auto"
    glossary_path: str = ""
    detector_conf: float = 0.3
    text_stroke_ratio: float = 0.08
    text_margin: float = 0.08
    min_font_size: int = 10
    max_font_size: int = 128
    export_format: str = "png"
    export_jpeg_quality: int = 90
    export_conflict: str = "rename"
    models_dir: str = ""
    single_key_shortcuts: bool = True
    first_run_complete: bool = False
    window_x: int | None = None
    window_y: int | None = None
    window_width: int | None = None
    window_height: int | None = None
    recent_projects: list[str] = field(default_factory=list)
    remote_enabled: bool = False
    remote_bind: str = "0.0.0.0"
    remote_port: int = 8765
    remote_devices: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._normalize()

    def _normalize(self) -> None:
        self.theme = _choice(self.theme, _THEMES, "system")
        self.ui_scale = _as_int(self.ui_scale, 100, 100, 150)
        source = _raw_text(self.source_lang, "en")
        target = _raw_text(self.target_lang, "ru")
        self.source_lang = source or "en"
        self.target_lang = target or "ru"
        self.llm_base_url = _raw_text(self.llm_base_url, "")
        self.llm_model = _raw_text(self.llm_model, "")
        self.llm_thinking = _as_bool(self.llm_thinking, False)
        self.llm_timeout = _as_int(self.llm_timeout, 300, 10, 3600)
        self.ocr_backend = _choice(self.ocr_backend, _OCR, "vlm")
        self.translator_backend = _choice(self.translator_backend, _TRANSLATORS, "llm")
        self.inpainter_backend = _choice(self.inpainter_backend, _INPAINTERS, "lama")
        self.reading_order = _choice(self.reading_order, _READING, "auto")
        self.translate_sfx = _as_bool(self.translate_sfx, False)
        # Явный sfx_mode в JSON уже выровнял флаг в from_dict.
        # Конструктор со старым True и дефолтным skip поднимаем до replace.
        mode = _choice(self.sfx_mode, _SFX_MODES, "skip")
        if mode == "skip" and self.translate_sfx:
            mode = "replace"
        self.sfx_mode = mode
        self.translate_sfx = mode == "replace"
        device = _raw_text(self.device, "auto")
        self.device = device or "auto"
        self.glossary_path = _raw_text(self.glossary_path, "")
        self.detector_conf = _as_float(self.detector_conf, 0.3, 0.05, 0.95)
        self.text_stroke_ratio = _as_float(self.text_stroke_ratio, 0.08, 0.0, 0.5)
        self.text_margin = _as_float(self.text_margin, 0.08, 0.0, 0.3)
        min_size = _as_int(self.min_font_size, 10, 8, 256)
        max_size = _as_int(self.max_font_size, 128, 8, 256)
        if min_size > max_size:
            max_size = min_size
        self.min_font_size = min_size
        self.max_font_size = max_size
        export_format = _raw_text(self.export_format, "png").lower()
        if export_format == "jpeg":
            export_format = "jpg"
        self.export_format = export_format if export_format in _EXPORT_FORMATS else "png"
        self.export_jpeg_quality = _as_int(self.export_jpeg_quality, 90, 1, 100)
        self.export_conflict = _choice(self.export_conflict, _EXPORT_CONFLICTS, "rename")
        self.models_dir = _raw_text(self.models_dir, "")
        self.single_key_shortcuts = _as_bool(self.single_key_shortcuts, True)
        self.first_run_complete = _as_bool(self.first_run_complete, False)
        self.window_x = _optional_int(self.window_x)
        self.window_y = _optional_int(self.window_y)
        width = _optional_int(self.window_width)
        height = _optional_int(self.window_height)
        self.window_width = None if width is None else max(1100, width)
        self.window_height = None if height is None else max(700, height)
        self.recent_projects = _recent(self.recent_projects)
        self.remote_enabled = _as_bool(self.remote_enabled, False)
        self.remote_bind = _bind_host(self.remote_bind)
        self.remote_port = _as_int(self.remote_port, 8765, 1, 65535)
        self.remote_devices = _devices(self.remote_devices)

    def get_api_key(self) -> str:
        return get_api_key()

    def set_api_key(self, value: str) -> bool:
        return set_api_key(value)

    def to_dict(self) -> dict:
        """Снимок без ключа API. Его можно класть в задание воркера."""
        self._normalize()
        return {
            "theme": self.theme,
            "ui_scale": self.ui_scale,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_thinking": self.llm_thinking,
            "llm_timeout": self.llm_timeout,
            "ocr_backend": self.ocr_backend,
            "translator_backend": self.translator_backend,
            "inpainter_backend": self.inpainter_backend,
            "reading_order": self.reading_order,
            "translate_sfx": self.translate_sfx,
            "sfx_mode": self.sfx_mode,
            "device": self.device,
            "glossary_path": self.glossary_path,
            "detector_conf": self.detector_conf,
            "text_stroke_ratio": self.text_stroke_ratio,
            "text_margin": self.text_margin,
            "min_font_size": self.min_font_size,
            "max_font_size": self.max_font_size,
            "export_format": self.export_format,
            "export_jpeg_quality": self.export_jpeg_quality,
            "export_conflict": self.export_conflict,
            "models_dir": self.models_dir,
            "single_key_shortcuts": self.single_key_shortcuts,
            "first_run_complete": self.first_run_complete,
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "recent_projects": list(self.recent_projects),
            "remote_enabled": self.remote_enabled,
            "remote_bind": self.remote_bind,
            "remote_port": self.remote_port,
            "remote_devices": [dict(item) for item in self.remote_devices],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> AppSettings:
        """Собрать настройки из словаря. Неизвестные поля игнорируются."""
        if not isinstance(data, dict):
            return cls()
        payload = dict(data)
        if "sfx_mode" not in payload:
            if _as_bool(payload.get("translate_sfx"), False):
                payload["sfx_mode"] = "replace"
        else:
            mode = str(payload.get("sfx_mode") or "skip").strip().lower()
            if mode not in _SFX_MODES:
                mode = "skip"
            payload["sfx_mode"] = mode
            payload["translate_sfx"] = mode == "replace"
        known = {item.name for item in cls.__dataclass_fields__.values()}
        filtered = {key: value for key, value in payload.items() if key in known}
        return cls(**filtered)

    @classmethod
    def load(cls, path: str | Path) -> tuple[AppSettings, list[str]]:
        """Прочитать файл. Нет файла — дефолты. Битый JSON переименовывается в ``.bad``."""
        file_path = Path(path)
        if not file_path.exists():
            return cls(), []
        try:
            raw = file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return cls(), [_quarantine_warning(file_path)]
        if not isinstance(data, dict):
            return cls(), [_quarantine_warning(file_path)]

        warnings: list[str] = []
        schema = _schema_value(data)
        if schema is None or schema < SCHEMA_VERSION:
            warnings.append("Настройки без схемы обновлены до версии 1")
        elif schema > SCHEMA_VERSION:
            warnings.append(
                f"Схема настроек {schema} новее поддерживаемой {SCHEMA_VERSION}, "
                "прочитаны известные поля"
            )
        return cls.from_dict(data), warnings

    def save(self, path: str | Path) -> None:
        """Записать JSON схемы 1. Ключ API в файл не попадает."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        payload["schema"] = SCHEMA_VERSION
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        file_path.write_text(text + "\n", encoding="utf-8")

    def to_config(self) -> Config:
        """Поля пайплайна. Пустой ``llm_base_url`` остаётся пустым, без дефолта из Config."""
        self._normalize()
        config = Config()
        config.source_lang = self.source_lang
        config.target_lang = self.target_lang
        config.llm_model = self.llm_model
        config.llm_thinking = self.llm_thinking
        config.llm_timeout = self.llm_timeout
        config.ocr_backend = self.ocr_backend
        config.translator_backend = self.translator_backend
        config.inpainter_backend = self.inpainter_backend
        config.reading_order = self.reading_order
        config.sfx_mode = self.sfx_mode
        config.translate_sfx = self.sfx_mode == "replace"
        config.device = self.device
        config.glossary_path = self.glossary_path
        config.detector_conf = self.detector_conf
        config.text_stroke_ratio = self.text_stroke_ratio
        config.text_margin = self.text_margin
        config.min_font_size = self.min_font_size
        config.max_font_size = self.max_font_size
        config.llm_base_url = self.llm_base_url
        return config


def _quarantine_warning(path: Path) -> str:
    try:
        renamed = _quarantine(path)
    except OSError as exc:
        return f"Повреждённый файл настроек не прочитан ({exc})"
    return f"Повреждённый файл настроек переименован в {renamed.name}"
