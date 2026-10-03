"""Живой запрос к LLM. В обычном прогоне пропускается маркером slow."""

import urllib.request

import pytest
from PIL import Image

from src.config import Config
from src.utils.llm_client import LlmClient


def _server_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/models", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.requires_llm
def test_server_returns_json():
    config = Config()
    if not _server_up(config.llm_base_url):
        pytest.skip(f"LLM недоступен: {config.llm_base_url}")
    client = LlmClient(
        config.llm_base_url,
        model=config.llm_model,
        thinking=False,
        timeout=60,
    )
    image = Image.new("RGB", (32, 32), "white")
    payload = client.chat_json(
        prompt='Return JSON {"ok": true}.',
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        schema_name="ping",
        images=[image],
        max_tokens=32,
    )
    assert "ok" in payload
