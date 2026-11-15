"""Проверки импорта публичных примеров без моделей и сети."""

import json

import pytest
from PIL import Image

from scripts import update_readme_examples as examples


@pytest.fixture
def public_run(tmp_path, monkeypatch):
    public = tmp_path / 'public'
    public.mkdir()
    monkeypatch.setattr(examples, 'EXAMPLES', public)
    monkeypatch.setattr(examples, 'git_revision', lambda: {'commit': 'fixed'})
    source = public / 'source.png'
    Image.new('RGB', (40, 60), 'white').save(source)
    case = dict(id='english', input='source.png', sha256=examples.digest(source),
                source_lang='en', target_lang='ru', credit='Test author')
    manifest = {'settings': {'neutral_text_colors': True}}
    config = tmp_path / 'settings.json'
    examples.write_json(config, dict(llm_base_url='http://localhost:8989/v1',
                                    llm_model='test', llm_api_key='SECRET'))
    folder = tmp_path / 'work'
    examples.prepare_run(folder, [case], manifest, config)
    page = folder / 'run' / '001'
    page.mkdir(parents=True)
    Image.new('RGB', (40, 60), 'gray').save(page / 'result.png')
    row = dict(id='001', image='english.png', status='done', seconds=1, ocr='vlm',
               translator='llm', regions=0, warnings=[],
               source_sha256=examples.digest(folder / 'inputs' / 'english.png'),
               result_sha256=examples.digest(page / 'result.png'))
    examples.write_json(page / 'regions.json', {'source_path': 'PRIVATE', 'regions': []})
    config_value = json.loads((folder / 'config.json').read_text('utf-8'))
    examples.write_json(folder / 'run' / 'manifest.json', dict(run_id='test', config=config_value))
    examples.write_json(folder / 'run' / 'report.json', {'images': [row]})
    examples.write_json(folder / 'run' / 'summary.json', dict(state='completed', updated_at='now'))
    return folder, case, manifest, public


def test_preparation_clears_key_and_import_preserves_result_pixels(public_run):
    folder, case, manifest, public = public_run
    assert 'SECRET' not in (folder / 'config.json').read_text('utf-8')
    examples.import_run(folder, [case], manifest)
    assert examples.digest(public / 'translated/english.png') == examples.digest(folder / 'run/001/result.png')
    report = json.loads((public / 'runs/english.json').read_text('utf-8'))
    assert report['effective_source_lang'] == 'auto'
    assert report['code']['commit'] == 'fixed'
    assert 'localhost' not in json.dumps(report)
    payload = json.loads((public / 'regions/english.json').read_text('utf-8'))
    assert payload['source_path'] == 'source.png'


@pytest.mark.parametrize('change', ['result', 'settings', 'input', 'running'])
def test_import_rejects_changed_or_unfinished_run_before_publication(public_run, change):
    folder, case, manifest, public = public_run
    if change == 'result':
        Image.new('RGB', (40, 60), 'red').save(folder / 'run/001/result.png')
    elif change == 'input':
        Image.new('RGB', (40, 60), 'red').save(folder / 'inputs/english.png')
    elif change == 'settings':
        manifest['settings']['neutral_text_colors'] = False
    else:
        examples.write_json(folder / 'run/summary.json', dict(state='running'))
    with pytest.raises(ValueError):
        examples.import_run(folder, [case], manifest)
    assert not (public / 'translated').exists()
