"""Клиент того же LAN API, которым пользуется расширение браузера."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RemoteCancelled(Exception):
    """Пользователь отменил локальный приём результата и серверную задачу."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def server_url(value: str) -> str:
    """Точный адрес API без секрета, query и учётных данных в URL."""
    text = str(value or "").strip().rstrip("/")
    parsed = urlsplit(text)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Нужен адрес сервера вида http://192.168.88.41:8765")
    parsed.port
    return text


class QuickRemoteClient:
    def __init__(self, url: str, token: str = "", *, poll_seconds: float = .6,
                 request_timeout: float = 60, job_timeout: float = 7200):
        self.url = server_url(url)
        self.token = token
        self.poll_seconds = poll_seconds
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        self.opener = build_opener(_NoRedirect())

    def _request(self, method, path, *, body=None, content_type=None, binary=False):
        headers = {"Accept": "image/png" if binary else "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                data = response.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise RuntimeError("Ответ сервера больше 64 МиБ")
                if binary:
                    return data
                return json.loads(data.decode("utf-8")) if data else {}
        except HTTPError as exc:
            text = exc.read(8192).decode("utf-8", errors="replace")
            try:
                message = json.loads(text).get("error") or text
            except (ValueError, AttributeError):
                message = text
            if exc.code == 401:
                message = "Нужно сопряжение с сервером: ПКМ → Сервер…"
            raise RuntimeError(f"Сервер HTTP {exc.code}: {message}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Сервер недоступен: {self.url} ({exc.reason if isinstance(exc, URLError) else exc})") from None
        except (ValueError, UnicodeError):
            raise RuntimeError("Сервер вернул некорректный ответ") from None

    def pair(self, code: str) -> str:
        if not re.fullmatch(r"\d{6}", str(code or "")):
            raise ValueError("Код сопряжения должен содержать 6 цифр")
        data = self._request("POST", "/v1/pair", body=json.dumps({"code": code, "name": "FastStone quick translate"}).encode(),
                             content_type="application/json")
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("Сервер не вернул токен сопряжения")
        return token.strip()

    def translate(self, source: Path, target_lang: str, *, fresh: bool,
                  cancel: threading.Event, progress) -> tuple[bytes, dict]:
        if not self.token:
            raise RuntimeError("Настройте сервер и сопряжение: ПКМ → Сервер…")
        if cancel.is_set():
            raise RemoteCancelled()
        health = self._request("GET", "/v1/health")
        limit = health.get("max_body_bytes", 20 * 1024 * 1024)
        if not isinstance(limit, int) or limit <= 0:
            limit = 20 * 1024 * 1024
        limit = min(limit, 64 * 1024 * 1024)
        if source.stat().st_size > limit:
            raise RuntimeError(f"Файл больше лимита сервера ({limit // (1024 * 1024)} МиБ)")
        boundary = "ilt-" + uuid.uuid4().hex
        fields = [("target_lang", target_lang)] + ([("fresh", "1")] if fresh else [])
        body = b"".join((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
                        for key, value in fields)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image{source.suffix.lower()}"\r\n'
                 'Content-Type: application/octet-stream\r\n\r\n').encode()
        body += source.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        if len(body) > limit:
            raise RuntimeError("Файл с полями запроса превышает лимит сервера")
        if cancel.is_set():
            raise RemoteCancelled()
        remote_id = ""
        try:
            response = self._request("POST", "/v1/translate", body=body,
                                     content_type=f"multipart/form-data; boundary={boundary}")
            remote_id = str(response.get("job_id") or "")
            if not re.fullmatch(r"[0-9a-fA-F]+", remote_id):
                raise RuntimeError("Сервер не вернул идентификатор задания")
            deadline = time.monotonic() + self.job_timeout
            while not cancel.is_set():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Истёк срок ожидания перевода с учётом очереди сервера")
                view = self._request("GET", f"/v1/jobs/{remote_id}?diagnostics=1")
                progress({**view, "remote_id": remote_id, "server_version": health.get("version", "")})
                status = view.get("status")
                if status == "done":
                    png = self._request("GET", f"/v1/jobs/{remote_id}/result", binary=True)
                    if cancel.is_set():
                        raise RemoteCancelled()
                    return png, {**view, "remote_id": remote_id, "server_version": health.get("version", "")}
                if status == "error":
                    raise RuntimeError(str(view.get("error") or "Ошибка перевода на сервере"))
                if status not in {"queued", "running"}:
                    raise RuntimeError("Неизвестный статус серверной задачи")
                cancel.wait(self.poll_seconds)
            raise RemoteCancelled()
        finally:
            if remote_id:
                try:
                    self._request("DELETE", f"/v1/jobs/{remote_id}")
                except RuntimeError:
                    # Ошибка очистки не отменяет уже полученный результат.
                    pass
