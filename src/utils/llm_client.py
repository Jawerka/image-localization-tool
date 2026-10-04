"""Минимальный клиент OpenAI-совместимого API (llama.cpp)."""

from __future__ import annotations

import base64
import io
import json
import re
import time
from typing import Any

from PIL import Image

from src.errors import StageError
from src.utils.logger import logger


class LlmError(StageError):
    """Ошибка запроса к языковой модели."""

    def __init__(self, message: str):
        super().__init__(message, stage="llm")


def strip_think(text: str) -> str:
    """Убрать блоки рассуждений <think>…</think>."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    lower = cleaned.lower()
    close_tag = "</think>"
    if close_tag in lower:
        cleaned = cleaned[lower.rfind(close_tag) + len(close_tag):]
    return cleaned.strip()


def parse_json_content(text: str) -> dict:
    """Достать JSON-объект из ответа модели."""
    cleaned = strip_think(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        value = json.loads(fenced.group(1))
        if isinstance(value, dict):
            return value

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        value = json.loads(cleaned[start:end + 1])
        if isinstance(value, dict):
            return value
    raise LlmError("Ответ модели не является JSON-объектом")


def encode_image_jpeg(image: Image.Image, quality: int = 85) -> str:
    """JPEG в base64 без переносов строк."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class LlmClient:
    """Chat Completions: картинки, json_schema, выключение thinking."""

    def __init__(
        self,
        base_url: str,
        model: str = "",
        thinking: bool = False,
        timeout: int = 300,
        session: Any = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.thinking = thinking
        self.timeout = timeout
        self._session = session
        self._resolved_model = model.strip()

    def _http(self):
        if self._session is not None:
            return self._session
        import requests
        return requests

    def list_models(self) -> list[str]:
        """Имена моделей с /v1/models."""
        response = self._http().get(
            f"{self.base_url}/models",
            timeout=min(15, self.timeout),
        )
        response.raise_for_status()
        payload = response.json()
        names = []
        for item in payload.get("data") or []:
            model_id = item.get("id")
            if model_id:
                names.append(str(model_id))
        return names

    def resolve_model(self) -> str:
        """Вернуть заданную модель или первую с сервера."""
        if self._resolved_model:
            return self._resolved_model
        names = self.list_models()
        if not names:
            raise LlmError("Сервер не вернул ни одной модели")
        self._resolved_model = names[0]
        logger.info(f"LLM model: {self._resolved_model}")
        return self._resolved_model

    def available(self) -> bool:
        """True, если /v1/models отвечает и модель известна."""
        try:
            self.resolve_model()
            return True
        except Exception as exc:
            logger.warning(f"LLM server unavailable: {exc}")
            return False

    def chat_json(
        self,
        prompt: str,
        schema: dict,
        schema_name: str,
        images: list[Image.Image] | None = None,
        max_tokens: int = 4096,
        *,
        system: str = "",
    ) -> dict:
        """Запрос с картинками и JSON-схемой. Несколько попыток.

        ``system`` — отдельное сообщение роли system. Пустая строка его не добавляет.
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._chat_once(
                    prompt, schema, schema_name, images or [], max_tokens, use_schema=True, system=system,
                )
            except LlmError as exc:
                last_error = exc
                if attempt == 0 and (
                    "response_format" in str(exc).lower() or "HTTP 400" in str(exc)
                ):
                    try:
                        return self._chat_once(
                            prompt,
                            schema,
                            schema_name,
                            images or [],
                            max_tokens,
                            use_schema=False,
                            system=system,
                        )
                    except Exception as inner:
                        last_error = inner
            except Exception as exc:
                last_error = exc
            time.sleep(1.0 * (attempt + 1))
        raise LlmError(f"Не удалось получить ответ LLM: {last_error}")

    def _chat_once(
        self,
        prompt: str,
        schema: dict,
        schema_name: str,
        images: list[Image.Image],
        max_tokens: int,
        use_schema: bool,
        system: str = "",
    ) -> dict:
        import requests

        content: str | list[dict] = prompt
        if images:
            content = [{"type": "text", "text": prompt}]
            for image in images:
                encoded = encode_image_jpeg(image)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                })

        messages: list[dict] = []
        if str(system or "").strip():
            messages.append({"role": "system", "content": str(system).strip()})
        messages.append({"role": "user", "content": content})
        payload: dict[str, Any] = {
            "model": self.resolve_model(),
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "messages": messages,
            "chat_template_kwargs": {"enable_thinking": bool(self.thinking)},
        }
        if use_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            }

        try:
            response = self._http().post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LlmError(str(exc)) from exc

        if response.status_code >= 400:
            body = response.text[:500]
            raise LlmError(f"HTTP {response.status_code}: {body}")

        data = response.json()
        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        text = message.get("content") or ""
        if not str(text).strip() and message.get("reasoning_content"):
            text = message["reasoning_content"]
        return parse_json_content(str(text))
