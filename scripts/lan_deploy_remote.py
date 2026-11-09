"""Проверка и применение LAN-деплоя; запускается через SSH без установки помощника."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid

TEMP_ROOT = Path('/tmp')


def digest(path):
    """Хеш файла без загрузки больших данных в память."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def checked_path(root, relative, roots):
    """Разрешены только обычные пути кода, без ссылок и выхода из корня."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] not in roots:
        raise ValueError('Недопустимый путь: ' + relative)
    target = root.joinpath(*rel.parts)
    for part in [target, *target.parents]:
        if part.is_symlink():
            raise ValueError('Ссылка в пути: ' + str(part))
        if part == root:
            break
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Путь вне установки')
    return target


def plan(request):
    """Настоящий dry run: только чтение, без загрузок и перезапуска службы."""
    root = Path(request['root'])
    if not root.is_absolute() or root in (Path('/'), Path('/opt')) or '..' in root.parts:
        raise ValueError('Недопустимый корень установки')
    if not root.is_dir() or any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError('Корень отсутствует или содержит ссылку')
    roots = ['src', 'web'] + (['tests'] if request.get('include_tests') else [])
    active = subprocess.run(['systemctl', 'is-active', request['service']], capture_output=True, text=True)
    if active.returncode != 0:
        raise RuntimeError('Служба не активна; автоматический деплой остановлен')
    work = subprocess.check_output(['systemctl', 'show', request['service'], '-p', 'WorkingDirectory', '--value'], text=True).strip()
    if Path(work).resolve() != root.resolve():
        raise ValueError('WorkingDirectory службы не совпадает с целью')
    before = {}
    changed = []
    for item in request['files']:
        target = checked_path(root, item['path'], roots)
        if target.exists() and not target.is_file():
            raise ValueError('Ожидался обычный файл: ' + item['path'])
        before[item['path']] = digest(target) if target.exists() else None
        if before[item['path']] != item['sha256']:
            changed.append(item['path'])
    data_bytes = sum(p.stat().st_size for p in (root/'data').rglob('*') if p.is_file() and not p.is_symlink()) if (root/'data').exists() else 0
    required = data_bytes + sum(i['size'] for i in request['files'])*3 + 32*1024*1024
    free = shutil.disk_usage(root).free
    if free < required:
        raise RuntimeError('Недостаточно места для stage и резервной копии')
    return dict(root=str(root), changed=changed, before=before, free_bytes=free,
                required_bytes=required, backup_data_bytes=data_bytes, service=request['service'])


def healthy(service):
    """Проверить службу и настоящий health API с ограниченным ожиданием."""
    for _ in range(45):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/v1/health', timeout=2) as response:
                if json.load(response).get('ready') is True:
                    subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError('Служба не прошла health check')


def deploy(request):
    """План, затем проверенный архив, резервная копия, применение и откат кода."""
    preview = plan(request)
    if request['mode'] == 'plan':
        return preview
    import fcntl
    root = Path(request['root'])
    lock_path = root.parent / ('.'+root.name+'-deploy.lock')
    if lock_path.is_symlink():
        raise ValueError('Файл блокировки является ссылкой')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preview = plan(request)
        if preview['before'] != request['expected_before']:
            raise RuntimeError('Сервер изменился после dry run; требуется новый план')
        archive = Path(request['archive'])
        if archive.parent != TEMP_ROOT or archive.is_symlink() or not archive.name.startswith('ilt-deploy-'):
            raise ValueError('Недопустимый временный архив')
        if digest(archive) != request['archive_sha256']:
            raise ValueError('Хеш архива не совпадает')
        roots = ['src', 'web'] + (['tests'] if request.get('include_tests') else [])
        expected = {i['path']: i for i in request['files']}
        backup_parent = root.parent / ('.'+root.name+'-deploy-backups')
        if backup_parent.is_symlink():
            raise ValueError('Каталог резервных копий является ссылкой')
        with tempfile.TemporaryDirectory(prefix='.ilt-stage-', dir=root.parent) as stage_name:
            stage = Path(stage_name)
            with tarfile.open(archive) as package:
                members = package.getmembers()
                if len(members) != len(expected) or {m.name for m in members} != set(expected):
                    raise ValueError('Состав архива не совпадает с манифестом')
                for member in members:
                    if not member.isfile() or member.size != expected[member.name]['size']:
                        raise ValueError('В архиве не обычный файл или неверный размер')
                    dest = checked_path(stage, member.name, roots)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as source, dest.open('wb') as output:
                        shutil.copyfileobj(source, output)
                    if digest(dest) != expected[member.name]['sha256']:
                        raise ValueError('Неверный хеш файла: ' + member.name)
            backup = backup_parent / (time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            backup_parent.mkdir(mode=0o700, exist_ok=True)
            backup.mkdir(mode=0o700)
            applied = []
            stopped = False
            try:
                subprocess.run(['systemctl', 'stop', request['service']], check=True)
                stopped = True
                if (root/'data').exists():
                    shutil.copytree(root/'data', backup/'data', symlinks=True)
                for config in ['config.json', '.env']:
                    if (root/config).is_file():
                        shutil.copy2(root/config, backup/config, follow_symlinks=False)
                (backup/'plan.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
                for relative in preview['changed']:
                    target = checked_path(root, relative, roots)
                    if target.exists():
                        saved = backup/'code'/relative
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, saved)
                for relative in preview['changed']:
                    target = checked_path(root, relative, roots)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage/relative, target)
                    applied.append(relative)
                subprocess.run(['systemctl', 'restart', request['service']], check=True)
                healthy(request['service'])
                for relative in expected:
                    if digest(checked_path(root, relative, roots)) != expected[relative]['sha256']:
                        raise RuntimeError('Установленный код не совпал с манифестом')
            except Exception:
                if applied:
                    subprocess.run(['systemctl', 'stop', request['service']], check=False)
                for relative in reversed(applied):
                    target = checked_path(root, relative, roots)
                    if preview['before'][relative] is None:
                        target.unlink()
                    else:
                        shutil.copy2(backup/'code'/relative, target)
                if stopped:
                    subprocess.run(['systemctl', 'restart', request['service']], check=True)
                    healthy(request['service'])
                raise
            finally:
                archive.unlink(missing_ok=True)
    return dict(ok=True, backup=str(backup), changed=preview['changed'], health_ready=True)
