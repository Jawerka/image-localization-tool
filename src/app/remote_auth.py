"""Коды сопряжения, хеши токенов устройств и лимит запросов.

Сырой токен нигде не хранится: в устройстве и в keyring только SHA-256.
Для проверки хватает списка устройств; keyring необязателен.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_CODE_TTL = 300.0
DEFAULT_RATE_LIMIT = 30
DEFAULT_RATE_WINDOW = 60.0

_KEYRING_SERVICE = "ImageLocalizationTool"


def hash_token(token: str) -> str:
    """SHA-256 токена в hex. Сырой токен не сохраняется."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    """hmac.compare_digest хеша и token_hash. Пустая строка и несовпадение — False."""
    if not isinstance(token, str) or not isinstance(token_hash, str):
        return False
    if not token or not token_hash:
        return False
    try:
        return hmac.compare_digest(hash_token(token), token_hash)
    except Exception:
        return False


@dataclass
class Device:
    """Устройство: id, имя, хеш токена и время создания. Сырого токена нет."""

    id: str
    name: str
    token_hash: str
    created: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "token_hash": self.token_hash,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Device:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            token_hash=str(data["token_hash"]),
            created=float(data["created"]),
        )


class Pairing:
    """Одноразовый шестизначный код. Новый вызов сменяет неиспользованный код."""

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        ttl: float = DEFAULT_CODE_TTL,
    ):
        self._clock = clock or time.time
        self._ttl = ttl
        self._code: str | None = None
        self._expires = 0.0

    def issue_code(self) -> str:
        """Новый код из 6 цифр (с ведущими нулями). Живёт ttl секунд, одно использование."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._code = code
        self._expires = self._clock() + self._ttl
        return code

    def current_code(self) -> str | None:
        """Уже выданный код, если он ещё не использован и не просрочен.

        Новый код не выдаёт: опрос может звать метод, не сменяя код.
        """
        if self._code is None or self._clock() >= self._expires:
            return None
        return self._code

    def redeem(self, code: str) -> str | None:
        """Сырой токен или None, если кода нет, он неверен, просрочен или уже использован.

        Успех сжигает код. Неверный код не трогает ещё живой код.
        """
        current = self._code
        if current is None or self._clock() >= self._expires:
            return None
        if not isinstance(code, str):
            return None
        try:
            matched = hmac.compare_digest(code, current)
        except Exception:
            return None
        if not matched:
            return None
        self._code = None
        return secrets.token_urlsafe()


def make_device(
    token: str,
    *,
    name: str = "",
    clock: Callable[[], float] | None = None,
) -> Device:
    """Устройство с новым id (uuid4 hex) и token_hash. Сырой токен не записывается."""
    now = time.time() if clock is None else clock()
    return Device(
        id=uuid.uuid4().hex,
        name=name,
        token_hash=hash_token(token),
        created=float(now),
    )


def find_device(devices: list, token: str) -> Device | None:
    """Первое устройство, чей хеш совпал. Элементы — Device или dict с теми же ключами."""
    for item in devices:
        device = item if isinstance(item, Device) else Device.from_dict(item)
        if token_matches(token, device.token_hash):
            return device
    return None


def revoke(devices: list, device_id: str) -> list[Device]:
    """Новый список без этого id. Хеш в keyring удаляется, если хранилище доступно.

    Неизвестный id возвращает те же устройства как объекты Device.
    """
    forget_hash(device_id)
    kept: list[Device] = []
    for item in devices:
        device = item if isinstance(item, Device) else Device.from_dict(item)
        if device.id != device_id:
            kept.append(device)
    return kept


class RateLimiter:
    """Не больше limit обращений одного ключа за последние window секунд."""

    def __init__(
        self,
        limit: int = DEFAULT_RATE_LIMIT,
        window: float = DEFAULT_RATE_WINDOW,
        clock: Callable[[], float] | None = None,
    ):
        self._limit = limit
        self._window = window
        self._clock = clock or time.time
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        """True, пока ключ внутри лимита. Вызов сверх лимита не считается. Пустой ключ — False."""
        if not key:
            return False
        now = self._clock()
        recent = [
            stamp
            for stamp in self._hits.get(key, ())
            if now - stamp < self._window
        ]
        if len(recent) >= self._limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True


def _remote_username(device_id: str) -> str:
    return f"remote:{device_id}"


def remember_hash(device_id: str, token_hash: str) -> bool:
    """Записать в keyring только хеш (служба ImageLocalizationTool, имя remote:<id>).

    Нет модуля или хранилище отказало — False. Авторизация от keyring не зависит.
    """
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _remote_username(device_id), token_hash)
    except Exception:
        return False
    return True


def forget_hash(device_id: str) -> None:
    """Удалить запись keyring для устройства. Ошибки и отсутствие модуля глотаются."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, _remote_username(device_id))
    except Exception:
        return
