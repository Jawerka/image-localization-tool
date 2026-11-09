"""Безопасное обновление расширения: фиксированный артефакт, план и проверяемый откат."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

FILES = frozenset({"manifest.json", "background.js", "button-model.js", "log.js", "image-source.js",
    "inline-content.js", "native-swap.js", "safe-content.js", "ui.css", "popup.html", "popup.js",
    "options.html", "options.js", "chime.js", "offscreen.html", "offscreen.js",
    "icons/icon16.png", "icons/icon32.png", "icons/icon48.png", "icons/icon128.png"})


def digest(path):
    """Хеш файла без преобразований."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(path):
    """Запрет ссылок и junction во всём пути до разрешения имени."""
    path = Path(path).absolute()
    for part in [path, *path.parents]:
        reparse = part.exists() and bool(getattr(part.lstat(), 'st_file_attributes', 0) & 0x400)
        if part.is_symlink() or reparse:
            raise ValueError(f"Ссылка в пути: {part}")
    return path.resolve()


def snapshot(root, *, skip_locks=False):
    """Все файлы, включая пользовательские; ссылки запрещены."""
    root = checked(root)
    if root.exists() and not root.is_dir():
        raise ValueError(f"Не каталог: {root}")
    result = {}
    for path in sorted(root.rglob('*')):
        if skip_locks and path.name == 'LOCK':
            continue
        checked(path)
        if path.is_file():
            if path.stat().st_nlink > 1:
                raise ValueError(f"Жёсткая ссылка: {path}")
            result[path.relative_to(root).as_posix()] = {"sha256": digest(path), "size": path.stat().st_size}
    return result


def independent(*paths):
    """Артефакт, установка и отчёт не могут содержать друг друга."""
    resolved = [checked(path) for path in paths]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("Пересекающиеся пути")
    return resolved


def write_record(path, payload):
    """Контрольная сумма обнаруживает изменение сохранённого плана."""
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    Path(path).write_text(json.dumps({"sha256": hashlib.sha256(data).hexdigest(), "payload": payload},
                                   ensure_ascii=False, indent=2), encoding='utf-8')


def read_record(path):
    """Проверка целостности перед использованием плана/backup."""
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    data = json.dumps(record['payload'], sort_keys=True, ensure_ascii=False).encode()
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError("Изменён план или backup")
    return record['payload']


def artifact_files(artifact):
    files = snapshot(Path(artifact) / 'files')
    if not files or 'manifest.json' not in files or not set(files) <= FILES:
        raise ValueError("Артефакт вне allowlist или без manifest")
    manifest = json.loads((Path(artifact) / 'files/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('manifest_version') != 3:
        raise ValueError("Нужен manifest MV3")
    if files != read_record(Path(artifact) / 'artifact.json'):
        raise ValueError("Артефакт изменился")
    return files


def prepare(source, artifact):
    """Новая копия сборки; существующий артефакт не перезаписывается."""
    source, artifact = independent(source, artifact)
    files = snapshot(source)
    if not files or 'manifest.json' not in files or not set(files) <= FILES:
        raise ValueError("Сборка вне allowlist")
    if artifact.exists():
        raise ValueError("Артефакт уже существует")
    artifact.mkdir(parents=True)
    for relative in files:
        target = artifact / 'files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    write_record(artifact / 'artifact.json', files)
    artifact_files(artifact)
    return str(artifact)


def free_bytes(path):
    """Свободное место на ближайшем существующем родителе."""
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


STORES = ('Local Extension Settings', 'Sync Extension Settings', 'Managed Extension Settings')


def browser_roots():
    """Стандартные профили Windows; другие каталоги браузера не читаются."""
    local = os.environ.get('LOCALAPPDATA')
    if os.name != 'nt' or not local:
        return []
    return [Path(local) / relative for relative in (
        'Google/Chrome/User Data', 'Microsoft/Edge/User Data',
        'BraveSoftware/Brave-Browser/User Data')]


def normalized_target(path):
    """Сопоставление только точного абсолютного пути распакованного расширения."""
    return str(path).replace('\\', '/').rstrip('/').casefold()


def state_inventory(target):
    """Только хранилища своего ID; содержимое Preferences никогда не сохраняется."""
    matches = set()
    wanted = normalized_target(checked(target))
    for root in browser_roots():
        root = checked(root)
        if not root.exists():
            continue
        for profile in sorted(root.iterdir()):
            if not (profile.name == 'Default' or re.fullmatch(r'Profile \d+', profile.name)):
                continue
            checked(profile)
            if not profile.is_dir():
                continue
            for name in ('Preferences', 'Secure Preferences'):
                preference = checked(profile / name)
                if not preference.exists():
                    continue
                try:
                    settings = json.loads(preference.read_text(encoding='utf-8')).get('extensions', {}).get('settings', {})
                except (OSError, ValueError, AttributeError) as exc:
                    raise ValueError(f'Не удалось проверить профиль: {preference}') from exc
                if not isinstance(settings, dict):
                    raise ValueError(f'Некорректный индекс расширений: {preference}')
                for ident, item in settings.items():
                    if not isinstance(item, dict) or normalized_target(item.get('path', '')) != wanted:
                        continue
                    if not re.fullmatch(r'[a-p]{32}', ident):
                        raise ValueError('Некорректный ID расширения в профиле')
                    matches.add((str(profile), ident))
    rows = []
    for profile, ident in sorted(matches):
        stores = {}
        for kind in STORES:
            source = checked(Path(profile) / kind / ident)
            stores[kind] = {'exists': source.exists(), 'files': snapshot(source, skip_locks=True)}
        rows.append({'profile': profile, 'extension_id': ident, 'stores': stores})
    return rows


def state_sources(state):
    """Текущее состояние только ранее найденных собственных хранилищ."""
    rows = []
    for row in state:
        stores = {}
        for kind in STORES:
            source = checked(Path(row['profile']) / kind / row['extension_id'])
            stores[kind] = {'exists': source.exists(), 'files': snapshot(source, skip_locks=True)}
        rows.append(dict(row, stores=stores))
    return rows


def validate_state_roots(state, *paths):
    """Отчёт, артефакт и backup не должны находиться внутри профиля."""
    for row in state:
        for path in paths:
            independent(row['profile'], path)


def backup_state(state, backup):
    """Копирование только состояния найденного расширения без LOCK."""
    for index, row in enumerate(state):
        for kind, store in row['stores'].items():
            if not store['exists']:
                continue
            source = Path(row['profile']) / kind / row['extension_id']
            destination = Path(backup) / 'browser-state' / str(index) / kind / row['extension_id']
            destination.mkdir(parents=True)
            for name in store['files']:
                saved = destination / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, saved)
    verify_state_backup(state, backup)
    if state_sources(state) != state:
        raise ValueError('Состояние браузера изменилось при backup; установка не изменена')


def verify_state_backup(state, backup):
    """Проверка всех скопированных данных до записи кода или отката."""
    expected = {}
    for index, row in enumerate(state):
        for kind, store in row['stores'].items():
            directory = Path(backup) / 'browser-state' / str(index) / kind / row['extension_id']
            if store['exists'] and not directory.is_dir():
                raise ValueError('Отсутствует резервная копия состояния браузера')
            for name, value in store['files'].items():
                expected[f"{index}/{kind}/{row['extension_id']}/{name}"] = value
    if snapshot(Path(backup) / 'browser-state') != expected:
        raise ValueError('Повреждена резервная копия состояния браузера')


def make_plan(artifact, target, backup):
    artifact, target, backup = independent(artifact, target, backup)
    files = artifact_files(artifact)
    before = snapshot(target)
    browser_state = state_inventory(target)
    validate_state_roots(browser_state, artifact, target, backup)
    changes = [name for name in files if before.get(name) != files[name]]
    state_bytes = sum(file['size'] for row in browser_state for store in row['stores'].values()
                      for file in store['files'].values())
    required = sum(row['size'] for row in files.values()) + sum(row['size'] for row in before.values()) + state_bytes
    if free_bytes(target) < required or free_bytes(backup) < required:
        raise ValueError("Недостаточно свободного места")
    if backup.exists():
        raise ValueError("Каталог backup уже существует")
    return {"artifact": str(artifact), "target": str(target), "backup": str(backup),
            "files": files, "before": before, "changes": changes, "deletions": [],
            "browser_state": browser_state, "browser_state_bytes": state_bytes,
            "required_bytes": required, "protected": "Все файлы вне allowlist сохраняются; профиль браузера не меняется"}


def dry_run(artifact, target, backup, plan):
    """Не пишет в установку, backup или артефакт; сохраняет только отдельный план."""
    independent(artifact, target, backup, plan)
    payload = make_plan(artifact, target, backup)
    validate_state_roots(payload["browser_state"], plan)
    Path(plan).parent.mkdir(parents=True, exist_ok=True)
    write_record(plan, payload)
    return dict(payload, free_target_bytes=free_bytes(target), free_backup_bytes=free_bytes(backup))


def rollback(backup, *, _partial_write=False):
    """Восстановление только изменённых файлов с проверкой оригиналов до записи."""
    backup = checked(backup)
    record = read_record(backup / 'rollback.json')
    target = checked(record['target'])
    independent(backup, target)
    saved = snapshot(backup / 'files')
    if saved != record['before']:
        raise ValueError("Повреждена резервная копия")
    verify_state_backup(record.get('browser_state', []), backup)
    state_before = state_sources(record.get('browser_state', []))
    current = snapshot(target)
    for name in record['changes']:
        if not _partial_write and current.get(name) not in (record['files'][name], record['before'].get(name)):
            raise ValueError(f"После обновления изменён файл: {name}")
    for name in record['changes']:
        destination = target / name
        if name in record['before']:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / 'files' / name, destination)
        elif destination.exists():
            destination.unlink()
    restored = snapshot(target)
    if any(restored.get(name) != record['before'].get(name) for name in record['changes']):
        raise RuntimeError("Проверка отката не пройдена")
    if state_sources(state_before) != state_before:
        raise RuntimeError('Состояние браузера изменилось во время отката; профиль не перезаписывался')
    return {"rolled_back": True, "target": str(target), "browser_state_untouched": True}


def apply(plan):
    """Применяет точно просмотренный план после проверки backup."""
    plan = checked(plan)
    record = read_record(plan)
    independent(record['artifact'], record['target'], record['backup'], plan)
    validate_state_roots(record.get('browser_state', []), plan)
    if make_plan(record['artifact'], record['target'], record['backup']) != record:
        raise ValueError("Артефакт, установка или параметры изменились: повторите dry run")
    target, backup = Path(record['target']), Path(record['backup'])
    backup.mkdir(parents=True)
    (backup / 'files').mkdir()
    for name in record['before']:
        saved = backup / 'files' / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, saved)
    if snapshot(backup / 'files') != record['before']:
        raise ValueError("Backup не прошёл проверку; установка не изменена")
    backup_state(record['browser_state'], backup)
    write_record(backup / 'rollback.json', record)
    # Проверяется полный обратный план, включая отсутствие новых файлов до установки.
    read_record(backup / 'rollback.json')
    if (snapshot(target) != record['before'] or artifact_files(record['artifact']) != record['files']
            or state_inventory(target) != record['browser_state']):
        raise ValueError("Установка или артефакт изменились при backup")
    try:
        for name in record['changes']:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(record['artifact']) / 'files' / name, destination)
        installed = snapshot(target)
        expected = dict(record['before'], **record['files'])
        if installed != expected:
            raise RuntimeError("Хеши установки или пользовательских файлов изменились")
    except Exception:
        rollback(backup, _partial_write=True)
        raise
    return {"applied": True, "backup": str(backup), "changes": record['changes']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'dry-run', 'apply', 'rollback'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        result = prepare(args.source, args.artifact)
    elif args.mode == 'dry-run':
        result = dry_run(args.artifact, args.target, args.backup, args.plan)
    elif args.mode == 'apply':
        result = apply(args.plan)
    else:
        result = rollback(args.backup)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
