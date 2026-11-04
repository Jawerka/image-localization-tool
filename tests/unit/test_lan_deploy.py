"""План и откат LAN-деплоя на изолированных файлах, без настоящего SSH/systemd."""

import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest


@pytest.fixture
def remote(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2]/'scripts/lan_deploy_remote.py'
    spec = importlib.util.spec_from_file_location('lan_deploy_remote_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path/'app'
    (root/'src').mkdir(parents=True)
    (root/'data/projects').mkdir(parents=True)
    (root/'src/main.py').write_bytes(b'old code')
    (root/'data/projects/saved.json').write_bytes(b'user project')
    module.TEMP_ROOT = tmp_path/'uploads'
    module.TEMP_ROOT.mkdir()
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(flock=lambda *args: None, LOCK_EX=2, LOCK_NB=4))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='active\n')
    monkeypatch.setattr(module.subprocess, 'run', run)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: str(root))
    monkeypatch.setattr(module, 'healthy', lambda service: None)
    payload = b'new code'
    request = dict(mode='plan', root=str(root), service='ilt.service',
                   files=[dict(path='src/main.py', size=len(payload), sha256=hashlib.sha256(payload).hexdigest())])
    return module, root, request, calls


def package(module, request, payload=b'new code'):
    archive = module.TEMP_ROOT/'ilt-deploy-test.tar'
    with tarfile.open(archive, 'w') as out:
        info = tarfile.TarInfo(request['files'][0]['path'])
        info.size = len(payload)
        out.addfile(info, io.BytesIO(payload))
    request.update(mode='apply', archive=str(archive), archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())


def test_dry_run_is_read_only_and_reports_real_changes(remote):
    module, root, request, calls = remote
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = module.deploy(request)
    assert result['changed'] == ['src/main.py']
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert not list(root.parent.glob('.app-*'))
    assert calls == [['systemctl', 'is-active', 'ilt.service']]


@pytest.mark.parametrize('bad', ['../data/settings.json', 'data/settings.json', '/etc/passwd', 'src/../../data/settings.json'])
def test_plan_rejects_non_code_and_traversal(remote, bad):
    module, root, request, calls = remote
    request['files'][0]['path'] = bad
    with pytest.raises(ValueError):
        module.deploy(request)
    assert (root/'data/projects/saved.json').read_bytes() == b'user project'


def test_apply_backs_up_code_and_projects_before_replacement(remote):
    module, root, request, calls = remote
    request['expected_before'] = module.deploy(request)['before']
    package(module, request)
    result = module.deploy(request)
    assert (root/'src/main.py').read_bytes() == b'new code'
    backup = Path(result['backup'])
    assert (backup/'code/src/main.py').read_bytes() == b'old code'
    assert (backup/'data/projects/saved.json').read_bytes() == b'user project'
    assert (root/'data/projects/saved.json').read_bytes() == b'user project'
    assert calls.index(['systemctl', 'stop', 'ilt.service']) < calls.index(['systemctl', 'restart', 'ilt.service'])


def test_stale_dry_run_rejected_before_stopping_service(remote):
    module, root, request, calls = remote
    request['expected_before'] = module.deploy(request)['before']
    package(module, request)
    (root/'src/main.py').write_bytes(b'external edit')
    with pytest.raises(RuntimeError, match='dry run'):
        module.deploy(request)
    assert ['systemctl', 'stop', 'ilt.service'] not in calls
    assert (root/'src/main.py').read_bytes() == b'external edit'


def test_failed_health_rolls_back_code_and_preserves_projects(remote, monkeypatch):
    module, root, request, calls = remote
    request['expected_before'] = module.deploy(request)['before']
    package(module, request)
    outcomes = iter([False, True])
    def healthy(service):
        if not next(outcomes):
            raise RuntimeError('unhealthy candidate')
    monkeypatch.setattr(module, 'healthy', healthy)
    with pytest.raises(RuntimeError, match='unhealthy'):
        module.deploy(request)
    assert (root/'src/main.py').read_bytes() == b'old code'
    assert (root/'data/projects/saved.json').read_bytes() == b'user project'


@pytest.mark.parametrize('fault', ['hash', 'unknown-member', 'symlink', 'size'])
def test_invalid_archive_rejected_before_service_stop(remote, fault):
    module, root, request, calls = remote
    request['expected_before'] = module.deploy(request)['before']
    package(module, request)
    archive = Path(request['archive'])
    if fault == 'hash':
        request['archive_sha256'] = '0'*64
    else:
        with tarfile.open(archive, 'w') as out:
            info = tarfile.TarInfo('data/settings.json' if fault == 'unknown-member' else 'src/main.py')
            if fault == 'symlink':
                info.type = tarfile.SYMTYPE
                info.linkname = '../../data/projects/saved.json'
                out.addfile(info)
            else:
                payload = b'bad size' if fault == 'size' else b'new code'
                if fault == 'size':
                    payload += b'longer'
                info.size = len(payload)
                out.addfile(info, io.BytesIO(payload))
        request['archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        module.deploy(request)
    assert ['systemctl', 'stop', 'ilt.service'] not in calls
    assert (root/'src/main.py').read_bytes() == b'old code'
    assert (root/'data/projects/saved.json').read_bytes() == b'user project'


def test_insufficient_space_blocks_plan(remote, monkeypatch):
    module, root, request, calls = remote
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    with pytest.raises(RuntimeError, match='места'):
        module.deploy(request)
    assert not list(root.parent.glob('.app-*'))


def test_wrong_service_directory_blocks_plan(remote, monkeypatch):
    module, root, request, calls = remote
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: str(root/'other'))
    with pytest.raises(ValueError, match='WorkingDirectory'):
        module.deploy(request)
    assert ['systemctl', 'stop', 'ilt.service'] not in calls
