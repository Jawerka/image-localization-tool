"""Повтор перевода, если модель пропустила блок."""

from PIL import Image

from src.components.llm_translator import ArgosBlockTranslator, LlmTranslator, build_translation_prompt
from src.models import TextRegion


class _ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_json(self, **kwargs):
        del kwargs
        self.calls += 1
        return self.responses.pop(0)


def test_missing_block_is_translated_on_retry():
    client = _ScriptedClient([
        {"items": [{
            "id": 1,
            "speaker": "Ann",
            "speaker_gender": "female",
            "translation": "Привет",
        }]},
        {"items": [{
            "id": 2,
            "speaker": "",
            "speaker_gender": "unknown",
            "translation": "Конец",
        }]},
    ])
    regions = [
        TextRegion(id=1, bbox=(0, 0, 10, 10), text="Hello", block_type="dialogue"),
        TextRegion(id=2, bbox=(0, 20, 10, 10), text="End", block_type="narration"),
    ]
    LlmTranslator(client).translate(Image.new("RGB", (8, 8)), regions, "en", "ru")
    assert client.calls == 2
    assert regions[0].translation == "Привет"
    assert regions[0].speaker_gender == "female"
    assert regions[1].translation == "Конец"


def test_translate_subset_retries_empty_and_keeps_other_regions():
    client = _ScriptedClient([
        {"items": []},
        {"items": [{
            "id": 1,
            "speaker": "Ann",
            "speaker_gender": "female",
            "translation": "Привет",
        }, {
            "id": 2,
            "speaker": "",
            "speaker_gender": "unknown",
            "translation": "Чужой",
        }]},
    ])
    client.prompts = []
    original = client.chat_json

    def chat_json(**kwargs):
        client.prompts.append(kwargs["prompt"])
        return original(**kwargs)

    client.chat_json = chat_json
    regions = [
        TextRegion(id=1, bbox=(0, 0, 10, 10), text="Hello", block_type="dialogue", translation="старое"),
        TextRegion(id=2, bbox=(0, 20, 10, 10), text="End", block_type="narration", translation="Конец"),
    ]
    LlmTranslator(client).translate_subset(
        Image.new("RGB", (8, 8)),
        regions,
        {1},
        "en",
        "ru",
    )
    assert client.calls == 2
    assert "End" in client.prompts[0]
    assert "only for these ids: 1" in client.prompts[0]
    assert "sound effects" not in client.prompts[0]
    assert regions[0].translation == "Привет"
    assert regions[1].translation == "Конец"


def test_sfx_prompt_asks_for_onomatopoeia_and_caller_glossary_wins():
    seen = []

    def chat_json(**kwargs):
        seen.append(kwargs["prompt"])
        return {"items": [{
            "id": 1,
            "speaker": "",
            "speaker_gender": "unknown",
            "translation": "ПИФ",
        }]}

    client = _ScriptedClient([])
    client.chat_json = chat_json
    regions = [
        TextRegion(id=1, bbox=(0, 0, 10, 10), text="Pow!", block_type="sfx"),
    ]
    LlmTranslator(client).translate(
        Image.new("RGB", (8, 8)),
        regions,
        "en",
        "ru",
        glossary={"POW": "ПИФ"},
        translate_sfx=True,
    )
    prompt = seen[0]
    assert "Blocks marked [sfx] are sound effects" in prompt
    assert "short Russian onomatopoeia" in prompt
    assert "no explanations" in prompt
    assert "no quotes" in prompt
    assert "POW = ПИФ" in prompt
    assert "POW = БАХ" not in prompt
    assert "BANG = БАМ" in prompt
    assert "Agree grammatical gender" in prompt
    direct = build_translation_prompt(
        "en",
        "ru",
        regions,
        {"POW": "ПИФ"},
    )
    assert "short Russian onomatopoeia" in direct


class _FakeArgos:
    def __init__(self):
        self.texts = None

    def translate_texts_ordered(self, texts, source_lang, target_lang):
        del source_lang, target_lang
        self.texts = list(texts)
        return [f"tr:{text}" for text in texts]


def test_argos_sfx_lookup_skips_known_blocks(monkeypatch):
    service = _FakeArgos()
    monkeypatch.setattr(
        "src.components.translator.TranslatorService",
        lambda: service,
    )
    regions = [
        TextRegion(id=1, bbox=(0, 0, 10, 10), text="Bang!", block_type="sfx"),
        TextRegion(id=2, bbox=(0, 20, 10, 10), text="Hello", block_type="dialogue"),
    ]
    ArgosBlockTranslator().translate(
        Image.new("RGB", (8, 8)),
        regions,
        "en",
        "ru",
        translate_sfx=True,
    )
    assert regions[0].translation == "БАМ"
    assert service.texts == ["Hello"]
    assert regions[1].translation == "tr:Hello"
