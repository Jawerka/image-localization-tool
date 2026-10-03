"""Дисковый кэш PNG-результатов с вытеснением по суммарному размеру.

Каталог создаётся при записи. Рядом с ``{token}.png`` лежит ``index.json``:
размер каждого блоба и монотонная метка ``last_used``. Сеть не используется.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_BYTES = 512 * 1024 * 1024

_INDEX_NAME = "index.json"


def fingerprint_settings(parts: Mapping[str, object] | str) -> str:
    """Отпечаток настроек для ключа кэша.

    Строка возвращается обрезанной; пустая после обрезки остаётся пустой.
    Отображение — sha256 канонического JSON (ключи отсортированы).
    Любой другой тип — sha256 от ``str(parts)``.
    """
    if isinstance(parts, str):
        return parts.strip()
    if isinstance(parts, Mapping):
        payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashlib.sha256(str(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    """Ключ результата: хеш исходных байтов, языки и отпечаток настроек."""

    image_sha256: str
    source_lang: str
    target_lang: str
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "image_sha256", self.image_sha256.strip().lower())
        object.__setattr__(self, "source_lang", self.source_lang.strip().lower())
        object.__setattr__(self, "target_lang", self.target_lang.strip().lower())
        object.__setattr__(self, "fingerprint", self.fingerprint.strip())

    @staticmethod
    def digest(image: bytes) -> str:
        """sha256-hex байтов изображения."""
        return hashlib.sha256(image).hexdigest()

    @classmethod
    def build(cls, image: bytes, source_lang: str, target_lang: str, fingerprint: str) -> CacheKey:
        return cls(
            image_sha256=cls.digest(image),
            source_lang=source_lang,
            target_lang=target_lang,
            fingerprint=fingerprint,
        )

    def token(self) -> str:
        """Имя файла без суффикса: sha256 от полей ключа через ``|``."""
        raw = f"{self.image_sha256}|{self.source_lang}|{self.target_lang}|{self.fingerprint}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    size: int
    last_used: int


class ImageCache:
    """Кэш PNG в каталоге. При переполнении удаляет давно не использованные записи."""

    def __init__(self, directory: Path | str, max_bytes: int = DEFAULT_MAX_BYTES):
        self._directory = Path(directory)
        self._max_bytes = max_bytes
        self._entries: dict[str, _Entry] = {}
        self._clock = 0
        self._load()

    def get(self, key: CacheKey) -> bytes | None:
        """Байты PNG или None. Попадание делает запись самой новой."""
        token = key.token()
        entry = self._entries.get(token)
        if entry is None:
            return None
        path = self._png_path(token)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self._entries.pop(token, None)
            self._save()
            return None
        entry.last_used = self._bump()
        self._save()
        return data

    def put(self, key: CacheKey, png: bytes) -> None:
        """Записать PNG и вытеснять старые записи, пока сумма не превышает лимит.

        Блоб крупнее ``max_bytes`` не пишется, кэш остаётся прежним.
        Повтор того же ключа заменяет байты и считается самым новым.
        """
        if len(png) > self._max_bytes:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        token = key.token()
        _atomic_write(self._png_path(token), png)
        self._entries[token] = _Entry(size=len(png), last_used=self._bump())
        self._evict()
        self._save()

    @property
    def total_bytes(self) -> int:
        """Сумма размеров хранимых PNG."""
        return sum(item.size for item in self._entries.values())

    def __len__(self) -> int:
        """Число записей."""
        return len(self._entries)

    def _png_path(self, token: str) -> Path:
        return self._directory / f"{token}.png"

    def _index_path(self) -> Path:
        return self._directory / _INDEX_NAME

    def _bump(self) -> int:
        self._clock += 1
        return self._clock

    def _load(self) -> None:
        path = self._index_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        raw = data.get("entries")
        if not isinstance(raw, dict):
            return
        entries: dict[str, _Entry] = {}
        for token, item in raw.items():
            if not isinstance(token, str) or not isinstance(item, dict):
                continue
            try:
                size = int(item["size"])
                last_used = int(item["last_used"])
            except (KeyError, TypeError, ValueError):
                continue
            entries[token] = _Entry(size=size, last_used=last_used)
        self._entries = entries
        try:
            self._clock = int(data.get("clock", 0))
        except (TypeError, ValueError):
            self._clock = 0
        if entries:
            self._clock = max(self._clock, max(item.last_used for item in entries.values()))

    def _evict(self) -> None:
        while self._entries and self.total_bytes > self._max_bytes:
            token = min(self._entries, key=lambda name: (self._entries[name].last_used, name))
            self._entries.pop(token)
            try:
                self._png_path(token).unlink()
            except FileNotFoundError:
                pass

    def _save(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "clock": self._clock,
            "entries": {
                token: {"last_used": item.last_used, "size": item.size}
                for token, item in self._entries.items()
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _atomic_write(self._index_path(), text.encode("utf-8"))


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
