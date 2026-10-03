"""Сбор глоссария говорящих из словарей регионов."""

from src.app.glossary import glossary_from_pages, merge_glossary, normalize_glossary


def test_two_speakers_sorted_with_empty_target_and_note():
    regions = [
        {"speaker": "Bob", "speaker_gender": "male"},
        {"speaker": "Alice", "speaker_gender": "female"},
    ]
    assert merge_glossary(regions) == [
        {"source": "Alice", "target": "", "gender": "female", "note": ""},
        {"source": "Bob", "target": "", "gender": "male", "note": ""},
    ]


def test_manual_entry_kept_when_speaker_is_absent():
    existing = [{
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }]
    regions = [
        {"speaker": "Bob", "speaker_gender": "male"},
        {"speaker": "Alice", "speaker_gender": "female"},
    ]
    result = merge_glossary(regions, existing)
    assert [item["source"] for item in result] == ["Alice", "Bob", "Carol"]
    assert result[2] == {
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }


def test_existing_target_and_gender_are_not_overwritten():
    existing = [{
        "source": "Alice",
        "target": "Алиса",
        "gender": "female",
        "note": "заметка",
    }]
    regions = [{"speaker": "Alice", "speaker_gender": "male"}]
    assert merge_glossary(regions, existing) == [{
        "source": "Alice",
        "target": "Алиса",
        "gender": "female",
        "note": "заметка",
    }]


def test_empty_speaker_and_non_dict_are_skipped():
    class _Region:
        speaker = "Zoe"
        speaker_gender = "female"

    regions = [
        {"speaker": "  ", "speaker_gender": "male"},
        {"speaker": "", "speaker_gender": "female"},
        {"speaker_gender": "female"},
        {"speaker": None, "speaker_gender": "male"},
        _Region(),
        "not-a-dict",
        None,
        {"speaker": "Ann"},
        {"speaker": " Bob ", "speaker_gender": " male "},
    ]
    assert merge_glossary(regions) == [
        {"source": "Ann", "target": "", "gender": "", "note": ""},
        {"source": "Bob", "target": "", "gender": "male", "note": ""},
    ]


def test_region_gender_fills_only_empty_existing_gender():
    existing = [{
        "source": "Alice",
        "target": "Алиса",
        "gender": "",
        "note": "заметка",
    }]
    regions = [
        {"speaker": "Alice", "speaker_gender": "  "},
        {"speaker": "Alice", "speaker_gender": "female"},
        {"speaker": "Alice", "speaker_gender": "male"},
    ]
    assert merge_glossary(regions, existing) == [{
        "source": "Alice",
        "target": "Алиса",
        "gender": "female",
        "note": "заметка",
    }]


def test_first_non_empty_region_gender_does_not_flap():
    regions = [
        {"speaker": "Alice", "speaker_gender": ""},
        {"speaker": "Alice", "speaker_gender": "female"},
        {"speaker": "Alice", "speaker_gender": "male"},
    ]
    assert merge_glossary(regions) == [{
        "source": "Alice",
        "target": "",
        "gender": "female",
        "note": "",
    }]


def test_order_is_deterministic_including_manual_entries():
    regions = [
        {"speaker": "Bob", "speaker_gender": "male"},
        {"speaker": "alice", "speaker_gender": "female"},
        {"speaker": "Alice", "speaker_gender": "female"},
    ]
    existing = [
        {"source": "Carol", "target": "Кэрол", "gender": "female", "note": "героиня"},
        {"source": "bob", "target": "Боб", "gender": "", "note": ""},
    ]
    first = merge_glossary(regions, existing)
    second = merge_glossary(list(reversed(regions)), list(reversed(existing)))
    assert first == second
    assert [item["source"] for item in first] == ["Alice", "alice", "Bob", "bob", "Carol"]
    assert first[2]["gender"] == "male"
    assert first[2]["target"] == ""
    # «bob» и «Bob» — разные source: пол региона Bob сюда не подставляется.
    assert first[3]["target"] == "Боб"
    assert first[3]["gender"] == ""
    manual = [
        {"source": "Zoe", "target": "Зои", "gender": "", "note": ""},
        {"source": "Amy", "target": "Эми", "gender": "female", "note": ""},
    ]
    assert [item["source"] for item in merge_glossary([], manual)] == ["Amy", "Zoe"]


def test_merge_does_not_mutate_existing():
    existing = [{
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }]
    snapshot = [dict(item) for item in existing]
    merge_glossary([{"speaker": "Alice", "speaker_gender": "female"}], existing)
    assert existing == snapshot


def test_normalize_glossary_drops_empty_source_and_fills_defaults():
    entries = [
        {"source": "Zoe", "note": "позже"},
        {"source": "  "},
        {"source": ""},
        {"target": "без имени"},
        None,
        "bad",
        {"source": "Amy"},
        {"source": "Zoe", "target": "другая", "gender": "male"},
        {"source": " Bob ", "gender": " male "},
    ]
    assert normalize_glossary(None) == []
    assert normalize_glossary(entries) == [
        {"source": "Zoe", "target": "", "gender": "", "note": "позже"},
        {"source": "Amy", "target": "", "gender": "", "note": ""},
        {"source": "Bob", "target": "", "gender": "male", "note": ""},
    ]


def test_glossary_from_pages_reads_regions_and_document():
    pages = [
        {"id": "idx", "source_path": "a.png", "name": "a.png"},
        {
            "status": "done",
            "document": {
                "version": 1,
                "regions": [
                    {"id": 1, "speaker": "Alice", "speaker_gender": "female"},
                    {"speaker": "   "},
                    "bad",
                ],
            },
        },
        {"regions": [{"speaker": "Bob", "speaker_gender": "male"}]},
        {
            "regions": [{"speaker": "Dave", "speaker_gender": "male"}],
            "document": {"regions": [{"speaker": "Eve", "speaker_gender": "female"}]},
        },
        None,
    ]
    existing = [{
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }]
    result = glossary_from_pages(pages, existing)
    assert [item["source"] for item in result] == ["Alice", "Bob", "Carol", "Dave", "Eve"]
    assert result[2]["target"] == "Кэрол"

    conflict = [{
        "regions": [{"speaker": "Alice", "speaker_gender": "female"}],
        "document": {"regions": [{"speaker": "Alice", "speaker_gender": "male"}]},
    }]
    assert glossary_from_pages(conflict)[0]["gender"] == "female"
    assert glossary_from_pages([{"id": "only"}], existing) == [{
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }]


def test_store_glossary_keeps_manual_and_reads_document(tmp_path):
    from PIL import Image

    from src.app.document import PageDocument
    from src.app.store import ProjectStore
    from src.models import TextRegion

    store = ProjectStore(tmp_path)
    project = store.create_project("Глава", "en", "ru")
    image = tmp_path / "page.png"
    Image.new("RGB", (8, 8), "white").save(image)
    page = store.add_sources(project["id"], [image])[0]
    document = PageDocument(
        regions=[
            TextRegion(
                id=1,
                bbox=(0, 0, 4, 4),
                text="Hi",
                speaker="Alice",
                speaker_gender="female",
            ),
        ],
    )
    store.write_document(project["id"], page["id"], document)
    store.write_glossary(project["id"], [{
        "source": "Carol",
        "target": "Кэрол",
        "gender": "female",
        "note": "героиня",
    }])
    view = store.glossary_view(project["id"])
    assert [item["source"] for item in view] == ["Alice", "Carol"]
    carol = next(item for item in view if item["source"] == "Carol")
    assert carol["target"] == "Кэрол"
    assert carol["note"] == "героиня"
    assert store.read_glossary(project["id"])[0]["source"] == "Carol"
