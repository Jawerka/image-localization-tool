"""LAN-деплой: обязательный настоящий dry run, проверенный архив и откат."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def manifest(roots):
    """Только код; кэш и ссылки не попадают в обновление."""
    files = []
    for directory in roots:
        if not (ROOT/directory).is_dir() or (ROOT/directory).is_symlink():
            raise ValueError('Каталог исходников отсутствует или является ссылкой: '+directory)
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_symlink():
                raise ValueError('Ссылка в исходниках: '+str(path))
            if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            files.append(dict(path=path.relative_to(ROOT).as_posix(), size=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='append', required=True)
    parser.add_argument('--user', default='root')
    parser.add_argument('--proxy-jump', default='pve.30')
    parser.add_argument('--remote-root', default='/opt/image-localization-tool')
    parser.add_argument('--service', default='ilt.service')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--include-tests', action='store_true')
    parser.add_argument('--report', default='')
    args = parser.parse_args()
    for value in [*args.host, args.user, args.service, args.proxy_jump]:
        if value and (not re.fullmatch(r'[A-Za-z0-9_.@:-]+', value) or value.startswith('-')):
            raise ValueError('Недопустимый SSH-параметр')
    options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=yes']
    if args.proxy_jump:
        options += ['-J', args.proxy_jump]
    helper = (ROOT/'scripts/lan_deploy_remote.py').read_text(encoding='utf-8')
    request = dict(mode='plan', root=args.remote_root, service=args.service,
                   include_tests=args.include_tests, files=manifest(['src', 'web']+(['tests'] if args.include_tests else [])))

    def remote(host, payload):
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        program = "import base64,json\nREQUEST=json.loads(base64.b64decode('"+encoded+"'))\n"+helper+'\nprint(json.dumps(deploy(REQUEST)))\n'
        result = subprocess.run(['ssh', *options, args.user+'@'+host, 'python3 -'],
                                input=program, capture_output=True, encoding='utf-8', timeout=600)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'SSH helper failed')
        return json.loads(result.stdout)

    host = None
    preview = None
    failures = []
    for candidate in args.host:
        try:
            preview = remote(candidate, request)
            host = candidate
            break
        except Exception as exc:
            failures.append(str(exc))
    if host is None:
        raise RuntimeError('; '.join(failures))
    print('DRY RUN: '+args.user+'@'+host+':'+args.remote_root, flush=True)
    print(json.dumps(preview, ensure_ascii=False, indent=2), flush=True)
    report = dict(host=host, dry_run=preview)
    if not args.dry_run:
        if not preview['changed']:
            report['applied'] = dict(ok=True, changed=[], note='Код уже совпадает; служба не перезапускалась')
        else:
            (ROOT/'output').mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='ilt-lan-', dir=ROOT/'output') as temporary:
                archive = Path(temporary)/'update.tar'
                with tarfile.open(archive, 'w') as package:
                    for item in request['files']:
                        package.add(ROOT/item['path'], arcname=item['path'], recursive=False)
                remote_archive = '/tmp/ilt-deploy-'+uuid.uuid4().hex+'.tar'
                subprocess.run(['scp', *options, str(archive), args.user+'@'+host+':'+remote_archive], check=True, timeout=180)
                request.update(mode='apply', archive=remote_archive,
                               archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), expected_before=preview['before'])
                report['applied'] = remote(host, request)
                print(json.dumps(report['applied'], ensure_ascii=False, indent=2), flush=True)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
