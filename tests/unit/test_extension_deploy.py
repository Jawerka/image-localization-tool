"""Поведенческие проверки деплоя на временной установке без сети."""
import json
import shutil
from pathlib import Path

import pytest

from scripts import extension_deploy as deploy


def fixture(tmp_path):
    source = tmp_path / 'source'
    source.mkdir(parents=True)
    (source / 'manifest.json').write_text(json.dumps({'manifest_version': 3}), encoding='utf-8')
    (source / 'background.js').write_bytes(b'new code')
    artifact, target = tmp_path / 'artifact', tmp_path / 'install'
    deploy.prepare(source, artifact)
    target.mkdir()
    (target / 'background.js').write_bytes(b'old code')
    (target / 'data').mkdir()
    (target / 'data/project.json').write_bytes(b'user project')
    (target / 'options.js').write_bytes(b'legacy code remains')
    return artifact, target, tmp_path / 'backup', tmp_path / 'plan.json'


def test_dry_run_does_not_write_installation_or_backup(tmp_path):
    artifact, target, backup, plan = fixture(tmp_path)
    before = deploy.snapshot(target)
    preview = deploy.dry_run(artifact, target, backup, plan)
    assert deploy.snapshot(target) == before
    assert not backup.exists()
    assert preview['deletions'] == []
    assert preview['free_target_bytes'] >= preview['required_bytes']
    assert preview['target'] == str(target.resolve())


def test_missing_installation_is_not_created_by_dry_run(tmp_path):
    artifact, target, backup, plan = fixture(tmp_path)
    missing = tmp_path / 'missing/install'
    deploy.dry_run(artifact, missing, backup, plan)
    assert not missing.parent.exists()


def test_apply_backup_and_rollback_preserve_unmanaged_files(tmp_path):
    artifact, target, backup, plan = fixture(tmp_path)
    before = deploy.snapshot(target)
    deploy.dry_run(artifact, target, backup, plan)
    deploy.apply(plan)
    assert (target / 'background.js').read_bytes() == b'new code'
    assert deploy.snapshot(backup / 'files') == before
    assert (target / 'data/project.json').read_bytes() == b'user project'
    (target / 'personal.txt').write_bytes(b'created after deploy')
    deploy.rollback(backup)
    assert (target / 'background.js').read_bytes() == b'old code'
    assert not (target / 'manifest.json').exists()
    assert (target / 'personal.txt').read_bytes() == b'created after deploy'
    assert (target / 'options.js').read_bytes() == b'legacy code remains'


@pytest.mark.parametrize('change', ['artifact', 'target', 'plan'])
def test_stale_or_modified_plan_refused_before_backup(tmp_path, change):
    artifact, target, backup, plan = fixture(tmp_path)
    deploy.dry_run(artifact, target, backup, plan)
    if change == 'artifact':
        (artifact / 'files/background.js').write_bytes(b'tampered')
    elif change == 'target':
        (target / 'background.js').write_bytes(b'user changed code')
    else:
        record = json.loads(plan.read_text(encoding='utf-8'))
        record['payload']['changes'] = []
        plan.write_text(json.dumps(record), encoding='utf-8')
    before = deploy.snapshot(target)
    with pytest.raises(ValueError):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before
    assert not backup.exists()


def test_corrupt_backup_refuses_rollback_before_writing(tmp_path):
    artifact, target, backup, plan = fixture(tmp_path)
    deploy.dry_run(artifact, target, backup, plan)
    deploy.apply(plan)
    (backup / 'files/background.js').write_bytes(b'broken backup')
    before = deploy.snapshot(target)
    with pytest.raises(ValueError, match='копия'):
        deploy.rollback(backup)
    assert deploy.snapshot(target) == before


def test_failed_backup_copy_cannot_modify_installation(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    deploy.dry_run(artifact, target, backup, plan)
    before = deploy.snapshot(target)
    monkeypatch.setattr(deploy.shutil, 'copy2', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='Backup'):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before


def test_interrupted_install_rolls_back_partial_file(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    deploy.dry_run(artifact, target, backup, plan)
    before = deploy.snapshot(target)
    original = shutil.copy2

    def fail_once(source, destination, *args, **kwargs):
        if Path(source) == artifact / 'files/background.js':
            Path(destination).write_bytes(b'partial')
            raise OSError('simulated write failure')
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(deploy.shutil, 'copy2', fail_once)
    with pytest.raises(OSError, match='simulated'):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before


def test_protected_source_and_overlapping_roots_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir(parents=True)
    (source / 'manifest.json').write_text('{}')
    (source / 'data').mkdir()
    (source / 'data/key.txt').write_text('secret')
    with pytest.raises(ValueError, match='allowlist'):
        deploy.prepare(source, tmp_path / 'artifact')
    artifact, target, backup, plan = fixture(tmp_path / 'other')
    with pytest.raises(ValueError, match='Пересекающиеся'):
        deploy.dry_run(artifact, target, backup, target / 'plan.json')


def test_insufficient_space_refuses_dry_run(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    monkeypatch.setattr(deploy, 'free_bytes', lambda path: 0)
    with pytest.raises(ValueError, match='места'):
        deploy.dry_run(artifact, target, backup, plan)
    assert not plan.exists()
    assert not backup.exists()


@pytest.fixture(autouse=True)
def isolated_browser_profiles(monkeypatch):
    """Ни один тест не читает настоящий профиль пользователя."""
    monkeypatch.setattr(deploy, 'browser_roots', lambda: [])


def profile_fixture(tmp_path, target, monkeypatch):
    root = tmp_path / 'browser-root'
    profile = root / 'Default'
    profile.mkdir(parents=True)
    ident = 'a' * 32
    (profile / 'Secure Preferences').write_text(json.dumps({'private': 'never-export-this-secret',
        'extensions': {'settings': {ident: {'path': str(target)},
                                  'b' * 32: {'path': str(tmp_path / 'unrelated')}}}}), encoding='utf-8')
    store = profile / 'Local Extension Settings' / ident
    store.mkdir(parents=True)
    (store / '000001.ldb').write_bytes(b'private application settings')
    (store / 'LOCK').write_bytes(b'live lock')
    other = profile / 'Local Extension Settings' / ('b' * 32)
    other.mkdir(parents=True)
    (other / 'secret.ldb').write_bytes(b'unrelated private data')
    monkeypatch.setattr(deploy, 'browser_roots', lambda: [root])
    return profile, store, ident


def test_browser_state_targeted_backup_and_code_only_rollback(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    profile, store, ident = profile_fixture(tmp_path, target, monkeypatch)
    preview = deploy.dry_run(artifact, target, backup, plan)
    assert preview['browser_state_bytes'] == len(b'private application settings')
    assert len(preview['browser_state']) == 1
    assert 'never-export-this-secret' not in plan.read_text(encoding='utf-8')
    assert 'unrelated private data' not in plan.read_text(encoding='utf-8')
    assert not backup.exists()
    deploy.apply(plan)
    saved = backup / 'browser-state/0/Local Extension Settings' / ident
    assert (saved / '000001.ldb').read_bytes() == b'private application settings'
    assert not (saved / 'LOCK').exists()
    assert not list((backup / 'browser-state').rglob('secret.ldb'))
    (store / '000001.ldb').write_bytes(b'new user state after deploy')
    live_before = deploy.snapshot(profile)
    result = deploy.rollback(backup)
    assert result['browser_state_untouched'] is True
    assert deploy.snapshot(profile) == live_before
    assert (store / '000001.ldb').read_bytes() == b'new user state after deploy'


def test_browser_state_drift_refuses_apply_before_code_or_backup(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    _profile, store, _ident = profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    (store / '000001.ldb').write_bytes(b'changed')
    before = deploy.snapshot(target)
    with pytest.raises(ValueError, match='изменились'):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before
    assert not backup.exists()


def test_incomplete_browser_state_backup_blocks_code_writes(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    before = deploy.snapshot(target)
    original = shutil.copy2

    def incomplete(source, destination, *args, **kwargs):
        if 'browser-state' not in Path(destination).parts:
            return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(deploy.shutil, 'copy2', incomplete)
    with pytest.raises(ValueError, match='состояния браузера'):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before


def test_state_changes_during_backup_blocks_code_writes(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    _profile, store, _ident = profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    before = deploy.snapshot(target)
    original = shutil.copy2

    def changing(source, destination, *args, **kwargs):
        result = original(source, destination, *args, **kwargs)
        if 'browser-state' in Path(destination).parts:
            (store / '000001.ldb').write_bytes(b'changed while copying')
        return result

    monkeypatch.setattr(deploy.shutil, 'copy2', changing)
    with pytest.raises(ValueError, match='изменилось при backup'):
        deploy.apply(plan)
    assert deploy.snapshot(target) == before


def test_corrupt_browser_state_backup_blocks_code_rollback(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    profile, _store, ident = profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    deploy.apply(plan)
    (backup / 'browser-state/0/Local Extension Settings' / ident / '000001.ldb').write_bytes(b'corrupt')
    code_before, profile_before = deploy.snapshot(target), deploy.snapshot(profile)
    with pytest.raises(ValueError, match='состояния браузера'):
        deploy.rollback(backup)
    assert deploy.snapshot(target) == code_before
    assert deploy.snapshot(profile) == profile_before


def test_browser_lock_changes_do_not_invalidate_data_snapshot(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    _profile, store, _ident = profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    (store / 'LOCK').write_bytes(b'different lock bytes')
    deploy.apply(plan)
    assert (store / 'LOCK').read_bytes() == b'different lock bytes'


def test_unreadable_browser_state_refuses_before_writes(tmp_path, monkeypatch):
    artifact, target, backup, plan = fixture(tmp_path)
    _profile, store, _ident = profile_fixture(tmp_path, target, monkeypatch)
    deploy.dry_run(artifact, target, backup, plan)
    before = deploy.snapshot(target)
    original = deploy.snapshot

    def unreadable(root, **kwargs):
        if Path(root) == store:
            raise PermissionError('cannot read extension state')
        return original(root, **kwargs)

    monkeypatch.setattr(deploy, 'snapshot', unreadable)
    with pytest.raises(PermissionError):
        deploy.apply(plan)
    assert original(target) == before
    assert not backup.exists()
