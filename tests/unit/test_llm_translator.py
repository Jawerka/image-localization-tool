"""Повтор перевода, если модель пропустила блок."""

from PIL import Image

from src.components.llm_translator import (
    ArgosBlockTranslator,
    LlmTranslator,
    _retry_prompt,
    build_translation_prompt,
)
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
    assert "from en to ru" not in prompt
    assert "only in ru" in prompt
    assert "Blocks marked [sfx] are sound effects" in prompt
    assert "short ru onomatopoeia" in prompt
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
    assert "short ru onomatopoeia" in direct
    assert "from en to ru" not in direct


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


def test_retry_prompt_locks_target_language():
    regions = [TextRegion(id=3, bbox=(0, 0, 10, 10), text="こんにちは", block_type="dialogue")]
    prompt = _retry_prompt("ru", regions)
    assert "only in ru" in prompt
    assert "from ja to ru" not in prompt
    assert "3. [dialogue] こんにちは" in prompt


def test_english_target_skips_russian_sfx_glossary():
    regions = [TextRegion(id=1, bbox=(0, 0, 10, 10), text="Pow!", block_type="sfx")]
    prompt = build_translation_prompt("ja", "en", regions, None)
    assert "only in en" in prompt
    assert "BANG = БАМ" not in prompt
    assert "Polivanov" not in prompt
    assert "short en onomatopoeia" in prompt


def test_locked_translation_not_overwritten_by_llm():
    client = _ScriptedClient([
        {"items": [{
            "id": 1,
            "speaker": "Ann",
            "speaker_gender": "female",
            "translation": "Машинный",
        }, {
            "id": 2,
            "speaker": "",
            "speaker_gender": "unknown",
            "translation": "Новый",
        }]},
    ])
    regions = [
        TextRegion(
            id=1,
            bbox=(0, 0, 10, 10),
            text="Hello",
            block_type="dialogue",
            translation="Ручной",
            translation_locked=True,
        ),
        TextRegion(id=2, bbox=(0, 20, 10, 10), text="End", block_type="narration"),
    ]
    LlmTranslator(client).translate(Image.new("RGB", (8, 8)), regions, "en", "ru")
    assert regions[0].translation == "Ручной"
    assert regions[1].translation == "Новый"


def test_proofreading_changes_only_requested_automatic_translations():
    client = _ScriptedClient([{'items': [
        {'id': 1, 'translation': 'Она пришла домой.'},
        {'id': 2, 'translation': 'Нельзя менять'},
        {'id': 3, 'translation': 'Нельзя менять'},
        {'id': 99, 'translation': 'Лишний'},
    ]}])
    regions = [
        TextRegion(1, (0, 0, 40, 20), text='She came home.', translation='Она пришёл домой.', block_type='dialogue'),
        TextRegion(2, (0, 30, 40, 20), text='Hello', translation='Ручной перевод', block_type='dialogue', translation_locked=True),
        TextRegion(3, (0, 60, 40, 20), text='End', translation='Конец', block_type='narration'),
    ]
    LlmTranslator(client).proofread(regions, 'ru', region_ids={1, 2})
    assert [r.translation for r in regions] == ['Она пришла домой.', 'Ручной перевод', 'Конец']


def test_proofreading_partial_or_foreign_response_keeps_good_draft():
    client = _ScriptedClient([{'items': [
        {'id': 1, 'translation': ''}, {'id': 2, 'translation': 'A completely foreign sentence remains here.'},
    ]}])
    regions = [TextRegion(i, (0, i*20, 40, 20), text='Hello', translation='Привет', block_type='dialogue') for i in (1, 2, 3)]
    LlmTranslator(client).proofread(regions, 'ru')
    assert all(r.translation == 'Привет' for r in regions)


def test_pipeline_proofreading_failure_does_not_trigger_argos_fallback():
    from src.config import Config
    from src.page_pipeline import PagePipeline

    class Client:
        def chat_json(self, **kwargs):
            if kwargs['schema_name'] == 'translation_proofread':
                raise RuntimeError('Недоступна вычитка')
            return {'items': [{'id': 1, 'translation': 'Привет', 'speaker': '', 'speaker_gender': 'unknown'}]}

    regions = [TextRegion(1, (0, 0, 40, 20), text='Hello', block_type='dialogue')]
    translator = LlmTranslator(Client())
    pipeline = PagePipeline(Config(), translator=translator)
    warnings = []
    result = pipeline._translate(Image.new('RGB', (80, 80)), regions, 'en', 'ru', warnings)
    assert pipeline.translator is translator
    assert result[0].translation == 'Привет'
    assert any('Вычитка' in warning for warning in warnings)


def test_proofreading_reviews_each_block_independently_with_shared_context():
    client = _ScriptedClient([
        {'items': [{'id': 1, 'translation': 'Она пришла домой.'}]},
        {'items': [{'id': 2, 'translation': 'Сегодня холодно.'}]},
    ])
    regions = [
        TextRegion(1, (0, 0, 40, 20), text='She came home.', translation='Она пришёл домой.', block_type='dialogue'),
        TextRegion(2, (0, 30, 40, 20), text='It is cold today.', translation='Сегодня холодные.', block_type='dialogue'),
    ]
    LlmTranslator(client).proofread(regions, 'ru')
    assert client.calls == 2
    assert [r.translation for r in regions] == ['Она пришла домой.', 'Сегодня холодно.']


def test_cancel_during_proofreading_stops_requests_without_argos():
    import pytest
    from src.config import Config
    from src.errors import PipelineCancelled
    from src.page_pipeline import PagePipeline

    class Client:
        cancelled = False
        calls = 0
        def chat_json(self, **kwargs):
            self.calls += 1
            if kwargs['schema_name'] == 'translation_proofread':
                self.cancelled = True
            return {'items': [{'id': 1, 'translation': 'Привет'}, {'id': 2, 'translation': 'Конец'}]}

    client = Client()
    translator = LlmTranslator(client)
    pipeline = PagePipeline(Config(), translator=translator)
    regions = [TextRegion(i, (0, i*20, 40, 20), text=text, block_type='dialogue')
               for i, text in [(1, 'Hello'), (2, 'End')]]
    with pytest.raises(PipelineCancelled):
        pipeline._translate(Image.new('RGB', (80, 80)), regions, 'en', 'ru', [],
                            cancel_check=lambda: client.cancelled)
    assert pipeline.translator is translator
    assert client.calls == 2
