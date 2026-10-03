"""Клиент LLM без сети: разбор ответа и тело запроса."""

from PIL import Image

from src.utils.llm_client import LlmClient, parse_json_content, strip_think


class FakeResponse:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text or str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


class FakeSession:
    def __init__(self, content='{"ok": 1}'):
        self.content = content
        self.posts = []

    def get(self, url, timeout=0):
        return FakeResponse({"data": [{"id": "qwen-test"}, {"id": "alias"}]})

    def post(self, url, json=None, timeout=0):
        self.posts.append(json)
        return FakeResponse({"choices": [{"message": {"content": self.content}}]})


def test_strip_think_and_parse_fenced_json():
    assert strip_think("<think>hidden</think>\n{\"a\": 1}") == '{"a": 1}'
    assert parse_json_content("```json\n{\"a\": 2}\n```") == {"a": 2}


def test_resolve_model_uses_first_server_id():
    client = LlmClient("http://llm/v1", session=FakeSession())
    assert client.resolve_model() == "qwen-test"
    assert client.available()


def test_chat_json_sends_image_schema_and_disables_thinking():
    session = FakeSession('{"blocks": []}')
    client = LlmClient("http://llm/v1", model="fixed", thinking=False, session=session)
    image = Image.new("RGB", (8, 8), "white")
    payload = client.chat_json("read", {"type": "object"}, "ocr", images=[image])
    assert payload == {"blocks": []}
    body = session.posts[0]
    assert body["model"] == "fixed"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["type"] == "json_schema"
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
