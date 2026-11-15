"""Контракты очереди приёмки без обращения к моделям и серверу."""

import json
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from scripts import test_images as runner


@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    images = tmp_path / 'images'
    images.mkdir()
    (images / 'a.png').write_bytes(b'page a')
    (images / 'b.jpg').write_bytes(b'page b')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(dict(llm_api_key='PRIVATE-KEY', llm_base_url='http://localhost:8989/v1')))
    output = tmp_path / 'run'
    args = runner.parser().parse_args(['run', '--config', str(config), '--images-root', str(images), '--output', str(output)])
    monkeypatch.setattr(runner, 'code_hashes', lambda: {'src/test.py': 'fixed'})
    return args


def test_discovery_filters_masks_and_selects_group(tmp_path):
    for name in ('a.png', 'a_mask.png', 'bmsak.png', 'sound-ref/a.png', 'html/cover.png', 'other.txt'):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'test')
    assert [r['image'] for r in runner.discover(tmp_path)] == ['a.png', 'sound-ref/a.png']
    assert [r['image'] for r in runner.discover(tmp_path, ['sound-ref/*'])] == ['sound-ref/a.png']
    assert len(runner.discover(tmp_path, excludes=['sound-ref/*'])) == 1


def test_snapshot_has_no_key_and_dry_run_writes_nothing(setup_run, capsys):
    args = setup_run
    manifest = runner.prepare(args)
    assert 'PRIVATE-KEY' not in json.dumps(manifest)
    assert 'llm_api_key' not in manifest['config']
    assert manifest['config']['sfx_mode'] == 'replace'
    assert runner.main(['run', '--config', str(args.config), '--images-root', str(args.images_root),
                        '--output', str(args.output), '--dry-run']) == 0
    assert not args.output.exists()
    assert json.loads(capsys.readouterr().out)['api_key_used'] is False


@pytest.mark.parametrize('field', ['config', 'images', 'code_hashes', 'options', 'input_root'])
def test_resume_rejects_changed_conditions(setup_run, field):
    manifest = runner.prepare(setup_run)
    changed = dict(manifest, **{field: 'changed'})
    with pytest.raises(ValueError, match=field):
        runner.validate_resume(manifest, changed)


def test_api_key_in_url_rejected(setup_run):
    setup_run.config.write_text(json.dumps(dict(llm_base_url='http://user:SECRET@host/v1')))
    with pytest.raises(ValueError, match='пароль'):
        runner.prepare(setup_run)


def fake_executor(calls, fail=None):
    def execute(output, manifest, row):
        calls.append(row['image'])
        folder = output / row['id']
        folder.mkdir(exist_ok=True)
        if row['image'] == fail:
            return dict(row, status='error', error='Сбой теста', seconds=1)
        result = folder / 'result.png'
        result.write_bytes(b'fake rendered PNG')
        return dict(row, status='done', result_sha256=runner.digest(result), seconds=1, warnings=[])
    return execute


def test_queue_continues_after_error_resume_and_retry(setup_run, monkeypatch):
    args = setup_run
    args.output.mkdir()
    manifest = runner.prepare(args)
    calls = []
    monkeypatch.setattr(runner, 'execute_page', fake_executor(calls, fail='a.png'))
    assert runner.run_queue(args.output, manifest) == 1
    assert calls == ['a.png', 'b.jpg']
    assert runner.read_json(args.output / 'summary.json')['state'] == 'completed_with_errors'
    calls.clear()
    assert runner.run_queue(args.output, manifest) == 1
    assert not calls
    monkeypatch.setattr(runner, 'execute_page', fake_executor(calls))
    assert runner.run_queue(args.output, manifest, retry_errors=True) == 0
    assert calls == ['a.png']
    assert runner.read_json(args.output / 'summary.json')['done'] == 2
    events = [json.loads(line) for line in (args.output / 'events.jsonl').read_text('utf8').splitlines()]
    assert sum(e['event'] == 'page_started' for e in events) == 3


def test_changed_result_requires_retry(setup_run, monkeypatch):
    args = setup_run
    args.output.mkdir()
    manifest = runner.prepare(args)
    calls = []
    monkeypatch.setattr(runner, 'execute_page', fake_executor(calls))
    assert runner.run_queue(args.output, manifest) == 0
    (args.output / '001/result.png').write_bytes(b'corrupt')
    calls.clear()
    assert runner.run_queue(args.output, manifest) == 1
    assert not calls
    assert runner.run_queue(args.output, manifest, retry_errors=True) == 0
    assert calls == ['a.png']


def test_interruption_and_resume(setup_run, monkeypatch):
    args = setup_run
    args.output.mkdir()
    manifest = runner.prepare(args)
    monkeypatch.setattr(runner, 'execute_page', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert runner.run_queue(args.output, manifest) == 130
    assert runner.read_json(args.output / 'summary.json')['state'] == 'interrupted'
    calls = []
    monkeypatch.setattr(runner, 'execute_page', fake_executor(calls))
    assert runner.run_queue(args.output, manifest) == 0
    assert len(calls) == 2


def test_exclusive_lock(tmp_path):
    with runner.run_lock(tmp_path):
        with pytest.raises(ValueError, match='занят'):
            with runner.run_lock(tmp_path):
                pytest.fail('Вторая блокировка не должна работать')
    with runner.run_lock(tmp_path):
        pass


def test_stop_denied_aborts_queue(setup_run, monkeypatch):
    args = setup_run
    args.output.mkdir()
    calls = []
    def denied(output, manifest, row):
        calls.append(row['image'])
        (output / row['id']).mkdir()
        raise runner.ProcessStopError('Остановка запрещена')
    monkeypatch.setattr(runner, 'execute_page', denied)
    assert runner.run_queue(args.output, runner.prepare(args)) == 2
    assert calls == ['a.png']
    assert runner.read_json(args.output / 'summary.json')['state'] == 'stop_failed'


@pytest.mark.parametrize('content', ['broken json', '[]'])
def test_invalid_config_rejected_without_output(setup_run, content):
    args = setup_run
    args.config.write_text(content)
    assert runner.main(['run', '--config', str(args.config), '--images-root', str(args.images_root),
                        '--output', str(args.output)]) == 2
    assert not args.output.exists()


def test_worker_crash_and_timeout_become_page_errors(setup_run, monkeypatch):
    args = setup_run
    args.output.mkdir()
    manifest = runner.prepare(args)
    row = manifest['images'][0]
    monkeypatch.setattr(runner, 'run_process', lambda *a: 7)
    assert runner.execute_page(args.output, manifest, row)['status'] == 'error'
    def timeout(*args):
        raise subprocess.TimeoutExpired('worker', 1)
    monkeypatch.setattr(runner, 'run_process', timeout)
    result = runner.execute_page(args.output, manifest, row)
    assert result['status'] == 'error' and 'предел' in result['error']


def test_real_subprocess_timeout_and_crash(tmp_path):
    started = time.monotonic()
    with (tmp_path / 'log').open('w') as log:
        with pytest.raises(subprocess.TimeoutExpired):
            runner.run_process([sys.executable, '-c', 'import time; time.sleep(30)'], log, 1)
        assert time.monotonic() - started < 10
        assert runner.run_process([sys.executable, '-c', 'raise SystemExit(7)'], log, 5) == 7


def test_legacy_gallery_keeps_identity_and_escapes_script(tmp_path):
    rows = [dict(id='001', image='</script><script>alert(1)</script>.png', status='done', source_sha256='abc')]
    runner.write_json(tmp_path / 'report.json', rows)
    assert runner.main(['gallery', '--output', str(tmp_path)]) == 0
    page = (tmp_path / 'index.html').read_text('utf8')
    assert json.dumps({'run_id': tmp_path.name}) in page
    assert '\\u003c/script>' in page
    assert 'position:sticky' not in page and 'position:fixed' not in page
    assert 'id="download-bottom"' in page
    assert 'id="run-progress"' in page
    assert 'id="eta"' in page
    assert '/*PROGRESS*/' not in page
    assert (tmp_path / 'progress.js').is_file()


def test_gallery_eta_counts_errors_and_elapsed_current_page(tmp_path):
    from datetime import datetime, timedelta, timezone
    rows = [dict(id='001', image='a.png', status='done', seconds=100),
            dict(id='002', image='b.png', status='done', seconds=200),
            dict(id='003', image='c.png', status='error', seconds=60),
            dict(id='004', image='d.png', status='running'),
            dict(id='005', image='e.png', status='pending')]
    runner.write_json(tmp_path / 'summary.json', dict(run_id='eta-run', state='running'))
    timestamp = (datetime.now(timezone.utc)-timedelta(seconds=100)).isoformat()
    (tmp_path / 'events.jsonl').write_text(json.dumps(dict(event='page_started', id='004', timestamp=timestamp))+'\n', encoding='utf-8')
    progress = runner.gallery_progress(tmp_path, rows, 'eta-run')
    assert progress['done'] == 2 and progress['error'] == 1 and progress['total'] == 5
    assert 138 < progress['remaining_seconds'] <= 140
    assert progress['current_image'] == 'd.png'
    assert runner.gallery_progress(tmp_path, rows[3:], 'eta-run')['remaining_seconds'] is None
    runner.write_json(tmp_path / 'summary.json', dict(run_id='eta-run', state='interrupted'))
    assert runner.gallery_progress(tmp_path, rows, 'eta-run')['remaining_seconds'] is None


def test_gallery_watch_only_updates_gallery_and_finishes(tmp_path, monkeypatch):
    rows = [dict(id='001', image='a.png', status='done', source_sha256='abc', seconds=12)]
    runner.write_json(tmp_path / 'report.json', dict(run_id='same-run', images=rows))
    runner.write_json(tmp_path / 'summary.json', dict(run_id='same-run', state='completed'))
    before = (tmp_path / 'report.json').read_bytes()
    def unexpected(*args, **kwargs):
        raise AssertionError('Наблюдение не должно запускать обработку')
    monkeypatch.setattr(runner, 'execute_page', unexpected)
    assert runner.main(['gallery', '--output', str(tmp_path), '--watch']) == 0
    assert (tmp_path / 'report.json').read_bytes() == before
    assert (tmp_path / 'progress.js').read_text(encoding='utf-8').startswith('window.iltReviewProgress(')
    assert 'same-run' in (tmp_path / 'index.html').read_text(encoding='utf-8')


def test_background_returns_without_waiting(setup_run, monkeypatch):
    class Process:
        pid = 1234
    launched = []
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda command, **kw: launched.append((command, kw)) or Process())
    args = setup_run
    assert runner.main(['run', '--config', str(args.config), '--images-root', str(args.images_root),
                        '--output', str(args.output), '--background']) == 0
    command, options = launched[0]
    assert '--background' not in command
    assert options['stdin'] == subprocess.DEVNULL
    assert runner.read_json(args.output / 'summary.json')['state'] == 'queued'


def test_cli_rejects_changed_source_before_processing(setup_run, monkeypatch):
    args = setup_run
    monkeypatch.setattr(runner, 'execute_page', fake_executor([]))
    command = ['run', '--config', str(args.config), '--images-root', str(args.images_root), '--output', str(args.output)]
    assert runner.main(command) == 0
    (args.images_root / 'a.png').write_bytes(b'changed')
    assert runner.main(command) == 2


def test_explicit_paths_outside_root_keep_order_and_remove_duplicates(setup_run, tmp_path):
    args = setup_run
    external = tmp_path / 'другая папка' / 'внешний файл.png'
    external.parent.mkdir()
    external.write_bytes(b'external')
    args.images = [str(external), str(args.images_root / 'b.jpg'), str(external)]
    manifest = runner.prepare(args)
    assert [row['source_path'] for row in manifest['images']] == [str(external.resolve()), str((args.images_root / 'b.jpg').resolve())]
    assert manifest['images'][0]['image'] == external.as_posix()
    assert manifest['options']['selection'] == 'explicit'


@pytest.mark.parametrize('suffix', ['.txt', '.json'])
def test_list_file_bom_quotes_relative_paths_and_duplicates(setup_run, tmp_path, suffix):
    args = setup_run
    listing = tmp_path / ('список' + suffix)
    entries = ['images/b.jpg', 'images/a.png', 'images/b.jpg']
    value = json.dumps(entries, ensure_ascii=False) if suffix == '.json' else '\n"images/b.jpg"\nimages/a.png\nimages/b.jpg\n'
    listing.write_text(value, encoding='utf-8-sig')
    args.list_file = [listing]
    assert [r['image'] for r in runner.prepare(args)['images']] == ['b.jpg', 'a.png']


@pytest.mark.parametrize('entry', ['missing.png', 'https://example.org/page.png', 'not-image.txt'])
def test_invalid_explicit_input_rejected_before_writing(setup_run, entry):
    args = setup_run
    if entry == 'not-image.txt':
        path = args.images_root / entry
        path.write_text('text')
        entry = str(path)
    command = ['run', '--config', str(args.config), '--output', str(args.output), '--images', entry]
    assert runner.main(command) == 2
    assert not args.output.exists()


def test_list_json_requires_string_array(setup_run, tmp_path):
    listing = tmp_path / 'paths.json'
    for value in ({'images': []}, [123]):
        listing.write_text(json.dumps(value))
        setup_run.list_file = [listing]
        with pytest.raises(ValueError, match='список строк'):
            runner.prepare(setup_run)


def test_explicit_mask_excluded_and_other_filters_work(setup_run):
    args = setup_run
    mask = args.images_root / 'a_mask.png'
    mask.write_bytes(b'mask')
    args.images = [str(mask), str(args.images_root / 'a.png'), str(args.images_root / 'b.jpg')]
    args.exclude = ['b.jpg']
    assert [r['image'] for r in runner.prepare(args)['images']] == ['a.png']


def test_background_uses_snapshot_list_for_explicit_paths(setup_run, monkeypatch):
    launched = []
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda command, **kw: launched.append(command) or SimpleNamespace(pid=1))
    args = setup_run
    source = args.images_root / 'a.png'
    assert runner.main(['run', '--config', str(args.config), '--images-root', str(args.images_root),
                        '--output', str(args.output), '--images', str(source), '--background']) == 0
    command = launched[0]
    snapshot = Path(command[command.index('--list-file') + 1])
    assert runner.read_json(snapshot) == [str(source.resolve())]
    child_args = runner.parser().parse_args(command[2:])
    runner.validate_resume(runner.read_json(args.output / 'manifest.json'), runner.prepare(child_args))


def test_live_progress_and_heartbeat(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runner, 'HEARTBEAT_SECONDS', 0.05)
    status = runner.PROGRESS_MARKER + json.dumps(dict(stage=25, message='OCR'), ensure_ascii=False)
    script = f'import time; print({status!r},flush=True); print("library noise",flush=True); time.sleep(1.2)'
    with (tmp_path / 'log').open('w', encoding='utf8') as log:
        assert runner.run_process([sys.executable, '-c', script], log, 5, '[1/2] page.png') == 0
    printed = capsys.readouterr().out
    assert '[1/2] page.png | 25% OCR' in printed
    assert 'выполняется' in printed
    assert 'library noise' not in printed
    assert 'library noise' in (tmp_path / 'log').read_text('utf8')


def test_worker_processes_explicit_external_source(setup_run, tmp_path, monkeypatch, capsys):
    args = setup_run
    external = tmp_path / 'external.png'
    external.write_bytes(b'input')
    args.images = [str(external)]
    args.output.mkdir()
    (args.output / '001').mkdir()
    runner.write_json(args.output / 'manifest.json', runner.prepare(args))
    class Pipeline:
        def __init__(self, config):
            assert config.llm_api_key == ''
        def process(self, source, **kwargs):
            assert source == str(external.resolve())
            kwargs['progress_callback'](25, 'OCR')
            return SimpleNamespace(output_image=SimpleNamespace(save=lambda p: p.write_bytes(b'output')),
                regions=[], ocr_engine='vlm', translator_engine='llm', warnings=[], regions_payload=lambda: {})
    module = ModuleType('src.page_pipeline')
    module.PagePipeline = Pipeline
    monkeypatch.setitem(sys.modules, 'src.page_pipeline', module)
    runner.worker(args.output, '001')
    assert runner.read_json(args.output / '001/record.json')['status'] == 'done'
    assert runner.PROGRESS_MARKER in capsys.readouterr().out
