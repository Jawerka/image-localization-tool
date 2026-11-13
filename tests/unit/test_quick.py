"""Быстрое окно использует протокол расширения и не запускает локальный перевод."""

import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from src.app.jobs import JobQueue
from src.app.server import AppState, _api, _HttpError
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker
from src.app.quick_remote import QuickRemoteClient, RemoteCancelled


class FakeRemote:
    def __init__(self):
        self.release = threading.Event()
        self.calls = []
        self.cancelled = []
        self.active = 0
        self.max_active = 0

    def pair(self, code):
        if code != '123456':
            raise ValueError('Неверный код')
        return 'test-remote-secret'

    def translate(self, source, target, *, fresh, cancel, progress):
        self.calls.append((source, target, fresh))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            progress({'status': 'running', 'progress': 50, 'stage': 'translate', 'remote_id': 'aabb'})
            while not self.release.wait(.01):
                if cancel.is_set():
                    self.cancelled.append(str(source))
                    raise RemoteCancelled()
            if cancel.is_set():
                raise RemoteCancelled()
            if source.stem == 'fail':
                raise RuntimeError('На сервере нет модели')
            data = io.BytesIO()
            with Image.open(source) as image:
                image.convert('RGB').save(data, 'PNG')
            return data.getvalue(), {'server_version': 'test', 'label': 'Текст не найден'}
        finally:
            self.active -= 1


@pytest.fixture
def app(tmp_path):
    store = ProjectStore(tmp_path / 'data')
    project = store.create_project('Редактор', 'en', 'ru')
    state = AppState(AppSettings(), tmp_path / 'data/settings.json', store,
                     JobQueue(FakeWorker(synchronous=False)), project_id=project['id'])
    (store.root / 'quick-server-token.txt').write_text(state.settings.quick_server_url + '\ntest-remote-secret')
    state.fake_remote = FakeRemote()
    state.quick.client_factory = lambda *args: state.fake_remote
    yield state
    state.quick.close()
    state.fake_remote.release.set()
    if state.quick._thread:
        state.quick._thread.join(timeout=2)


def image(tmp_path, name='страница 1.png'):
    path = tmp_path / name
    Image.new('RGB', (20, 30), 'white').save(path)
    return str(path)


def call(app, action, **body):
    return _api(app, 'GET' if action == 'session' else 'POST', '/api/quick/' + action, body).payload


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Состояние не наступило')


def finish(app):
    app.fake_remote.release.set()
    wait_for(lambda: not call(app, 'session')['busy'])


def test_queue_duplicates_failure_and_editor_isolation(app, tmp_path):
    editor = app.project_id
    first = image(tmp_path)
    second = image(tmp_path, 'fail.png')
    third = image(tmp_path, 'third.bmp')
    session = call(app, 'accept', paths=[first, second, third, first])
    assert len(session['items']) == 3
    assert session['selected_id'] == session['items'][0]['id']
    wait_for(lambda: len(app.fake_remote.calls) == 1)
    assert app.queue.worker.calls == []
    assert app.store.open_project(editor)['pages'] == []
    finish(app)
    session = call(app, 'session')
    assert [x['status'] for x in session['items']] == ['done', 'error', 'done']
    assert 'нет модели' in session['items'][1]['error']
    call(app, 'accept', paths=[first])
    assert len(app.fake_remote.calls) == 3
    assert app.fake_remote.max_active == 1
    assert app.project_id == editor
    assert len(app.store.list_projects()) == 1


@pytest.mark.parametrize('suffix', ['png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff'])
def test_formats(app, tmp_path, suffix):
    result = call(app, 'accept', paths=[image(tmp_path, 'file.' + suffix)])
    assert result['items'][0]['status'] in {'running', 'queued'}
    assert app.queue.worker.calls == []


def test_invalid_inputs_never_submit(app, tmp_path):
    bad = tmp_path / 'bad.png'
    bad.write_bytes(b'broken')
    result = call(app, 'accept', paths=[str(bad), image(tmp_path, 'not-supported.gif'), str(tmp_path/'lost.jpg')])
    assert all(x['status'] == 'error' and x['error'] for x in result['items'])
    assert not app.fake_remote.calls
    with pytest.raises(ValueError):
        call(app, 'accept', paths='not a list')


def test_cancel_retry_remove_only_own_job(app, tmp_path):
    session = call(app, 'accept', paths=[image(tmp_path), image(tmp_path, 'b.png')])
    first, second = session['items']
    wait_for(lambda: len(app.fake_remote.calls) == 1)
    call(app, 'cancel', id=second['id'])
    assert call(app, 'session')['items'][0]['status'] == 'running'
    assert call(app, 'session')['items'][1]['status'] == 'cancelled'
    call(app, 'retry', id=second['id'])
    assert call(app, 'session')['items'][1]['job_id'] != second['job_id']
    call(app, 'remove', id=first['id'])
    finish(app)
    assert len(call(app, 'session')['items']) == 1
    assert app.fake_remote.max_active == 1
    assert not app.queue.worker.cancel_calls


def test_save_conflict_and_original_protected(app, tmp_path):
    original = image(tmp_path)
    item = call(app, 'accept', paths=[original])['items'][0]
    finish(app)
    dest = tmp_path / 'saved.png'
    call(app, 'save', id=item['id'], path=str(dest))
    with Image.open(dest) as result:
        assert result.format == 'PNG'
    with pytest.raises(_HttpError) as conflict:
        call(app, 'save', id=item['id'], path=str(dest))
    assert conflict.value.status == 409
    call(app, 'save', id=item['id'], path=str(dest), overwrite=True)
    with pytest.raises(ValueError):
        call(app, 'save', id=item['id'], path=original, overwrite=True)


def test_report_materials_and_no_secret(app, tmp_path, monkeypatch):
    monkeypatch.setattr('src.app.settings.get_api_key', lambda: 'super-secret-value')
    item = call(app, 'accept', paths=[image(tmp_path)])['items'][0]
    finish(app)
    with pytest.raises(ValueError):
        call(app, 'bug-report', id=item['id'], note='  ')
    logs = app.store.root / 'logs'
    logs.mkdir()
    (logs / 'app.log').write_text(f"{item['job_id']} super-secret-value test-remote-secret https://user:password@host/a?token=private\n", encoding='utf-8')
    report = Path(call(app, 'bug-report', id=item['id'], note='Неверный текст')['path'])
    assert report.parent == app.store.root / 'bug-reports'
    assert (report / 'result.png').is_file()
    payload = (report / 'report.json').read_text(encoding='utf-8')
    assert json.loads(payload)['note'] == 'Неверный текст'
    all_text = payload + (report / 'task.log').read_text(encoding='utf-8')
    assert all(secret not in all_text for secret in ['super-secret-value', 'test-remote-secret', 'password', 'private'])
    assert json.loads(payload)['processing'] == 'remote-v1'


def test_open_in_editor_creates_copy(app, tmp_path):
    previous = app.project_id
    item = call(app, 'accept', paths=[image(tmp_path)])['items'][0]
    finish(app)
    result = call(app, 'editor', id=item['id'])
    assert result['project']['id'] != previous
    assert app.store.open_project(previous)['pages'] == []
    assert len(result['pages']) == 1
    assert app.store.image_path(app.project_id, result['pages'][0]['id'], 'result').is_file()


def test_browser_quick_blocked(app):
    app.browser_origins = ('http://localhost',)
    with pytest.raises(_HttpError) as denied:
        call(app, 'accept', paths=['C:/private.png'])
    assert denied.value.status == 403


def test_report_redaction_preserves_json(app, tmp_path):
    item = call(app, 'accept', paths=[image(tmp_path)])['items'][0]
    finish(app)
    report = Path(call(app, 'bug-report', id=item['id'], note='Ошибка "token=hidden"\nhttps://u:p@host/path?q=hidden')['path'])
    payload = json.loads((report / 'report.json').read_text(encoding='utf-8'))
    assert 'hidden' not in payload['note']
    assert payload['settings']['quick_server_url'] == app.settings.quick_server_url
    assert payload['server_settings_available'] is False


def test_no_text_is_warning_not_error(app, tmp_path):
    call(app, 'accept', paths=[image(tmp_path)])
    finish(app)
    view = call(app, 'session')['items'][0]
    assert view['status'] == 'done'
    assert 'Текст не найден' in view['warnings']


def test_server_config_pairing_secret_and_no_local_fallback(app, tmp_path):
    (app.store.root / 'quick-server-token.txt').write_text('')
    item = call(app, 'accept', paths=[image(tmp_path)])['items'][0]
    assert item['status'] == 'error'
    assert 'сопряжение' in item['error']
    assert not app.queue.worker.calls
    result = call(app, 'server', url='http://192.168.88.41:8765', code='123456')
    assert result['server']['paired']
    assert 'test-remote-secret' not in json.dumps(result)
    call(app, 'retry', id=item['id'])
    finish(app)
    assert app.fake_remote.calls[0][2] is True


def test_real_extension_protocol_upload_poll_result_delete(tmp_path):
    from src.app.remote import RemoteServer

    source = Path(image(tmp_path, 'страница.bmp'))
    output = io.BytesIO()
    Image.new('RGB', (12, 15), 'red').save(output, 'PNG')
    requests = []

    def runner(job):
        requests.append((job.target_lang, job.image))
        job.finish(output.getvalue())

    server = RemoteServer(AppSettings(), cache_dir=tmp_path/'remote', runner=runner)
    port = server.start('127.0.0.1', 0)
    try:
        client = QuickRemoteClient(f'http://127.0.0.1:{port}', poll_seconds=.01)
        client.token = client.pair(server.pairing.issue_code())
        progress = []
        result, metadata = client.translate(source, 'ru', fresh=True, cancel=threading.Event(), progress=progress.append)
        assert result == output.getvalue()
        assert requests[0][0] == 'ru'
        assert requests[0][1] == source.read_bytes()
        assert progress and metadata['remote_id']
        assert metadata['diagnostics']['settings']['target_lang'] == 'ru'
        assert server.queue.view(metadata['remote_id'], '') is None
        assert not server.queue._jobs
    finally:
        server.shutdown()


def test_remote_cancel_propagates_to_server_worker(tmp_path):
    from src.app.desktop import DesktopApp
    from src.app.remote import RemoteServer
    from src.app.remote_auth import make_device

    store = ProjectStore(tmp_path/'server-data')
    worker = FakeWorker(store, synchronous=False)
    state = AppState(AppSettings(), tmp_path/'server-data/settings.json', store, JobQueue(worker))
    app = DesktopApp(state, None, None)
    remote = RemoteServer(state.settings, cache_dir=tmp_path/'remote', store=store)
    app.remote_api = remote
    app._bind_remote_runner(remote)
    device = make_device('token')
    job = remote.submit_image(device, Path(image(tmp_path)).read_bytes(), 'auto', 'ru')
    wait_for(lambda: len(worker.calls) == 1)
    submitted = worker.calls[0]
    assert remote.queue.delete(job.id, device.id)
    wait_for(lambda: submitted.id in worker.cancel_calls)
    assert state.queue.job_status(submitted.id) == 'cancelled'
    state.close()


def test_server_diagnostics_omit_secrets_and_are_opt_in(tmp_path):
    from src.app.remote import RemoteServer
    from src.app.remote_auth import make_device

    remote = RemoteServer(AppSettings(), cache_dir=tmp_path/'remote')
    device = make_device('secret-bearer')
    job = remote.submit_image(device, Path(image(tmp_path)).read_bytes(), 'auto', 'ru')
    remote.queue.note_diagnostics(job.id, settings={
        'llm_base_url': 'https://user:password@example.org/v1?api_key=private',
        'llm_api_key': 'secret-key', 'remote_devices': [{'token_hash': 'secret-hash'}], 'text_scale': 1.2,
    }, warnings=['Текст не найден'])
    assert 'diagnostics' not in remote.queue.view(job.id, device.id)
    diagnostics = remote.queue.view(job.id, device.id, diagnostics=True)['diagnostics']
    assert diagnostics['settings']['text_scale'] == 1.2
    assert diagnostics['warnings'] == ['Текст не найден']
    assert all(secret not in json.dumps(diagnostics) for secret in ['password', 'private', 'secret-key', 'secret-hash'])


def test_client_checks_upload_limit_before_post(tmp_path):
    client = QuickRemoteClient('http://127.0.0.1:1', 'token')
    calls = []

    def request(method, path, **kwargs):
        calls.append(path)
        return {'max_body_bytes': 4}

    client._request = request
    with pytest.raises(RuntimeError, match='лимита'):
        client.translate(Path(image(tmp_path)), 'ru', fresh=False, cancel=threading.Event(), progress=lambda _: None)
    assert calls == ['/v1/health']


def test_token_is_not_reused_for_different_server(app, tmp_path):
    app.settings.quick_server_url = 'http://other-server:8765'
    item = call(app, 'accept', paths=[image(tmp_path)])['items'][0]
    assert item['status'] == 'error'
    assert not app.fake_remote.calls
    assert call(app, 'session')['server']['paired'] is False


def test_server_address_roundtrips_settings_and_config(tmp_path):
    settings = AppSettings(quick_server_url='http://192.168.88.41:9999')
    path = tmp_path/'settings.json'
    settings.save(path)
    loaded, warnings = AppSettings.load(path)
    assert not warnings
    assert loaded.quick_server_url == settings.quick_server_url
    assert loaded.to_config().quick_server_url == settings.quick_server_url
