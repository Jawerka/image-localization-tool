"""Необязательная учётная запись web: хеш пароля и отзывные сессии в памяти."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path

from src.config import Config


class AccessDenied(ValueError):
    """Неверные данные владельца."""


class AccessLimited(ValueError):
    """Слишком много попыток за минуту."""


class WebAccess:
    """Одна учётная запись на редактор; режим и хеш сохраняются атомарно."""

    SESSION_SECONDS = 12 * 60 * 60

    def __init__(self, root: Path):
        self.path = Path(root) / "web-access.json"
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, float] = OrderedDict()
        self._attempts: deque[float] = deque()
        self.generation = 0
        self._record = {"schema": 1, "enabled": Config().web_auth_enabled,
                        "username": "", "salt": "", "password_hash": ""}
        if self.path.exists():
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or type(record.get("schema")) is not int or record.get("schema") != 1 or type(record.get("enabled")) is not bool:
                    raise ValueError("Неверная схема")
                username, salt, digest = (record.get(key) for key in ("username", "salt", "password_hash"))
                if not isinstance(username, str) or len(username) > 64 or username != username.strip() or any(ord(char) < 32 for char in username):
                    raise ValueError("Неверное имя")
                if not isinstance(salt, str) or not isinstance(digest, str):
                    raise ValueError("Неверный хеш")
                configured = bool(username and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 32)
                if salt != bytes.fromhex(salt).hex() or digest != bytes.fromhex(digest).hex():
                    raise ValueError("Неверное кодирование хеша")
                if (record["enabled"] or username or salt or digest) and not configured:
                    raise ValueError("Неполная учётная запись")
                self._record = {key: record[key] for key in self._record}
            except (OSError, ValueError, TypeError) as exc:
                raise RuntimeError("Не удалось прочитать data/web-access.json; восстановите файл из резервной копии") from exc

    def status(self) -> dict:
        """Только публичные метаданные без хеша и соли."""
        with self._lock:
            return {"enabled": self._record["enabled"], "configured": bool(self._record["password_hash"]),
                    "username": self._record["username"]}

    def authorized(self, token: str) -> bool:
        with self._lock:
            return not self._record["enabled"] or self._sessions.get(token, 0) > time.monotonic()

    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                              n=16384, r=8, p=1, dklen=32).hex()

    def _check(self, username: object, password: object) -> None:
        now = time.monotonic()
        while self._attempts and self._attempts[0] <= now - 60:
            self._attempts.popleft()
        if len(self._attempts) >= 10:
            raise AccessLimited("Слишком много попыток. Повторите через минуту")
        self._attempts.append(now)
        if not isinstance(username, str) or len(username) > 64 or not isinstance(password, str) or not 1 <= len(password) <= 256:
            raise AccessDenied("Неверный логин или пароль")
        record = self._record
        if not record["password_hash"]:
            raise AccessDenied("Неверный логин или пароль")
        digest = self._hash(password, record["salt"])
        if not hmac.compare_digest(username.encode(), record["username"].encode()) or not hmac.compare_digest(digest, record["password_hash"]):
            raise AccessDenied("Неверный логин или пароль")

    def _session(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.monotonic() + self.SESSION_SECONDS
        while len(self._sessions) > 256:
            self._sessions.popitem(last=False)
        return token

    def login(self, username: object, password: object) -> str:
        with self._lock:
            if self._record["enabled"]:
                self._check(username, password)
            return self._session()

    def logout(self, token: str) -> None:
        """Отозвать только сессию текущего браузера."""
        with self._lock:
            self._sessions.pop(token, None)

    def update(self, body: dict, session: str = "") -> tuple[dict, str]:
        """Повторная проверка доступа под блокировкой исключает гонку включения."""
        with self._lock:
            if self._record["enabled"]:
                if not self.authorized(session):
                    raise AccessDenied("Войдите в редактор заново")
            if self._record["password_hash"]:
                self._check(self._record["username"], body.get("current_password"))
            if type(body.get("enabled")) is not bool:
                raise ValueError("Укажите режим защиты")
            enabled = body["enabled"]
            username = body.get("username", self._record["username"])
            password = body.get("password", "")
            if not isinstance(username, str) or not isinstance(password, str):
                raise ValueError("Неверные поля учётной записи")
            username = username.strip()
            if len(username) > 64 or any(ord(char) < 32 for char in username):
                raise ValueError("Логин должен содержать от 1 до 64 символов")
            record = {**self._record, "enabled": enabled}
            if password:
                if not username or not 10 <= len(password) <= 256:
                    raise ValueError("Укажите логин и пароль от 10 до 256 символов")
                record["salt"] = secrets.token_hex(16)
                record["password_hash"] = self._hash(password, record["salt"])
                record["username"] = username
            elif enabled and not self._record["password_hash"]:
                raise ValueError("Для включения защиты задайте логин и пароль")
            elif record["password_hash"]:
                if not username:
                    raise ValueError("Укажите логин")
                record["username"] = username
            if enabled and not record["password_hash"]:
                raise ValueError("Сначала создайте учётную запись")
            self._save(record)
            self._record = record
            self.generation += 1
            self._sessions.clear()
            return self.status(), self._session()

    def _save(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".web-access-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
