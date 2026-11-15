"""Стандартный автономный прогон PagePipeline и галерея ручной приёмки."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import fnmatch
import hashlib
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'scripts/templates/review_gallery.html'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
PROGRESS_MARKER = 'ILT_PROGRESS\t'
HEARTBEAT_SECONDS = 30
sys.path.insert(0, str(ROOT))


class ProcessStopError(RuntimeError):
    """Среда запретила остановить дерево страницы; продолжать очередь нельзя."""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def atomic_text(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(value, encoding='utf-8')
    temporary.replace(path)


def event(output, kind, **details):
    with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(timestamp=now(), event=kind, **details), ensure_ascii=False) + '\n')


@contextmanager
def run_lock(output):
    """Блокировка ОС освобождается и после аварийного завершения процесса."""
    with (output / '.run.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Каталог занят другим прогоном') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def discover(input_root, includes=(), excludes=()):
    """Маски не становятся исходниками даже при явном совпадении группы."""
    if not input_root.is_dir():
        raise ValueError(f'Нет каталога исходников: {input_root}')
    paths = []
    for path in input_root.rglob('*'):
        relative = path.relative_to(input_root)
        name = relative.as_posix()
        if (not path.is_file() or path.suffix.lower() not in EXTENSIONS
                or 'html' in [p.lower() for p in relative.parts]
                or any(word in path.stem.lower() for word in ('mask', 'msak'))):
            continue
        if includes and not any(fnmatch.fnmatchcase(name, pattern) for pattern in includes):
            continue
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in excludes):
            continue
        if not path.resolve().is_relative_to(input_root.resolve()):
            raise ValueError(f'Ссылка ведёт за пределы набора: {name}')
        paths.append(path)
    return [dict(id=f'{index:03d}', image=p.relative_to(input_root).as_posix(), source_path=str(p.resolve()), source_sha256=digest(p))
            for index, p in enumerate(sorted(paths), 1)]


def path_list(path):
    """TXT: путь на строку; JSON: массив строк; относительные пути — от файла списка."""
    path = path.resolve()
    text = path.read_text(encoding='utf-8-sig')
    entries = json.loads(text) if path.suffix.lower() == '.json' else text.splitlines()
    if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
        raise ValueError(f'Ожидается список строк с локальными путями: {path}')
    paths = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if len(entry) >= 2 and entry[0] == entry[-1] and entry[0] in ('"', "'"):
            entry = entry[1:-1]
        if '://' in entry:
            raise ValueError(f'Ожидается локальный путь, а не URL: {entry}')
        item = Path(entry).expanduser()
        paths.append((path.parent / item).resolve())
    return paths


def select_images(args):
    """Явный список не расширяется соседними файлами; порядок первого появления сохранён."""
    selected = list(args.images)
    for listing in args.list_file:
        selected.extend(path_list(listing))
    if not args.images and not args.list_file:
        return discover(args.images_root.resolve(), args.include, args.exclude)
    rows, seen = [], set()
    root = args.images_root.resolve()
    for item in selected:
        if '://' in str(item):
            raise ValueError(f'Ожидается локальный путь, а не URL: {item}')
        path = Path(item).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'Нет файла изображения: {path}')
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError(f'Неподдерживаемый формат изображения: {path}')
        if any(word in path.stem.lower() for word in ('mask', 'msak')):
            continue
        identity = os.path.normcase(str(path))
        if identity in seen:
            continue
        seen.add(identity)
        name = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        if args.include and not any(fnmatch.fnmatchcase(name, pattern) for pattern in args.include):
            continue
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in args.exclude):
            continue
        rows.append(dict(id=f'{len(rows) + 1:03d}', image=name, source_path=str(path), source_sha256=digest(path)))
    return rows


def config_snapshot(path):
    from src.config import Config
    if not path.is_file() or not isinstance(read_json(path), dict):
        raise ValueError(f'Нужен существующий JSON конфигурации: {path}')
    config = Config.load(path)
    config.llm_api_key = ''
    config.ort_intra_op_threads = 4
    config.sfx_mode = 'replace'
    config.translate_sfx = True
    parsed = urlsplit(config.llm_base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Адрес LLM не должен содержать пароль, ключ или параметры запроса')
    return {k: v for k, v in asdict(config).items() if not k.startswith('_') and k != 'llm_api_key'}


def code_hashes():
    paths = list((ROOT / 'src').rglob('*.py')) + [Path(__file__).resolve(), TEMPLATE]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def prepare(args):
    config = config_snapshot(args.config.resolve())
    images = select_images(args)
    if not images:
        raise ValueError('В выбранной группе нет исходных изображений')
    return dict(schema_version=1, run_id=args.output.name + '-' + uuid.uuid4().hex[:8],
                created_at=now(), input_root=str(args.images_root.resolve()), config=config,
                code_hashes=code_hashes(), images=images,
                options=dict(include=args.include, exclude=args.exclude, page_timeout=args.page_timeout,
                             selection='explicit' if args.images or args.list_file else 'directory'),
                runtime=dict(python=sys.version, platform=sys.platform))


def validate_resume(saved, current):
    for field in ('schema_version', 'input_root', 'config', 'code_hashes', 'images', 'options'):
        if saved.get(field) != current.get(field):
            raise ValueError(f'Условия прогона изменились ({field}); используйте новый --output')


def records(output, manifest):
    rows = []
    for image in manifest['images']:
        record = output / image['id'] / 'record.json'
        row = read_json(record) if record.exists() else dict(image, status='pending')
        if any(row.get(k) != image[k] for k in ('id', 'image', 'source_sha256', 'source_path') if k in image):
            raise ValueError(f'Запись не соответствует исходнику: {image["image"]}')
        if row['status'] == 'done':
            result = output / image['id'] / 'result.png'
            if not result.is_file() or digest(result) != row.get('result_sha256'):
                row = dict(image, status='error', error='Итоговый PNG отсутствует или изменён; используйте --retry-errors')
        rows.append(row)
    return rows


def gallery_progress(output, rows, run_id):
    """Оценка остатка по завершённым страницам, с учётом текущей страницы."""
    rows = [r for r in rows if r.get('status') != 'excluded']
    summary_path = output / 'summary.json'
    summary = read_json(summary_path) if summary_path.exists() else {}
    if summary.get('run_id') != run_id:
        summary = {}
    done = sum(r['status'] == 'done' for r in rows)
    errors = sum(r['status'] == 'error' for r in rows)
    terminal = 'completed_with_errors' if errors else 'completed'
    state = summary.get('state', terminal if done + errors == len(rows) else 'unknown')
    durations = [float(r['seconds']) for r in rows if r['status'] in ('done', 'error')
                 and isinstance(r.get('seconds'), (float, int)) and r['seconds'] > 0]
    running = next((r for r in rows if r['status'] == 'running'), None)
    started = None
    # Старый уже запущенный runner не пишет время старта в report.json.
    events_path = output / 'events.jsonl'
    if running and events_path.exists():
        for line in events_path.read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get('event') == 'page_started' and item.get('id') == running['id']:
                started = item.get('timestamp')
    elapsed = 0
    if started:
        try:
            elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
        except (ValueError, TypeError):
            pass
    remaining = None
    if state == 'running' and durations:
        remaining = max(0, sum(durations) / len(durations) * (len(rows)-done-errors) - elapsed)
    return dict(run_id=run_id, state=state, total=len(rows), done=done, error=errors,
                generated_at=now(), remaining_seconds=remaining,
                current_image=running['image'] if running else None,
                pages=[{k: r[k] for k in ('id', 'status', 'result_sha256', 'error') if k in r} for r in rows])


def write_gallery_progress(output, rows, run_id):
    """Классический локальный script работает и при открытии через file://."""
    progress = gallery_progress(output, rows, run_id)
    data = json.dumps(progress, ensure_ascii=False).replace('<', '\\u003c')
    atomic_text(output / 'progress.js', 'window.iltReviewProgress(' + data + ');\n')
    return progress


def render_gallery(output, rows, run_id):
    """Прежние id и run_id сохраняют оценки уже открывавшейся галереи."""
    rows = [r for r in rows if r.get('status') != 'excluded']
    cards = []
    for row in rows:
        ident = str(row['id'])
        if not ident or any(c not in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-' for c in ident):
            raise ValueError('Некорректный идентификатор страницы')
        label = html.escape(row['image'], quote=True)
        media = (f'<a href="{ident}/result.png" target="_blank"><img loading="lazy" alt="{label}" src="{ident}/result.png"></a>'
                 if row['status'] == 'done' else f'<p class="pending">{html.escape(row.get("error", "Ожидает обработки"))}</p>')
        stars = ''.join(f'<button type="button" data-star="{n}" aria-label="Оценка {n}">★</button>' for n in range(1, 6))
        cards.append(f'<article data-id="{ident}"><h2>{label}</h2>{media}<div class="stars">{stars}<button type="button" data-star="0" class="reset">Сбросить</button></div><textarea aria-label="Комментарий" placeholder="Комментарий" rows="3"></textarea></article>')
    compact = [{k: r[k] for k in ('id', 'image', 'status', 'source_sha256', 'result_sha256') if k in r} for r in rows]
    def js(value):
        return json.dumps(value, ensure_ascii=False).replace('<', '\\u003c')
    page = TEMPLATE.read_text(encoding='utf-8').replace('<!--CARDS-->', '\n'.join(cards))
    page = page.replace('/*MANIFEST*/[]', js(compact)).replace('/*RUN*/{}', js(dict(run_id=run_id)))
    page = page.replace('/*PROGRESS*/{}', js(write_gallery_progress(output, rows, run_id)))
    atomic_text(output / 'index.html', page)


def watch_gallery(output):
    """Обновлять только статус уже запущенного старой версией прогона."""
    first = True
    while True:
        report = read_json(output / 'report.json')
        rows = report if isinstance(report, list) else report['images']
        run_id = output.name if isinstance(report, list) else report['run_id']
        if first:
            render_gallery(output, rows, run_id)
            first = False
        progress = write_gallery_progress(output, rows, run_id)
        if progress['state'] != 'running' and progress['state'] != 'queued':
            return 0
        time.sleep(5)


def publish(output, manifest, rows, state):
    counts = {status: sum(r['status'] == status for r in rows) for status in ('done', 'error', 'pending', 'running')}
    summary = dict(schema_version=1, run_id=manifest['run_id'], updated_at=now(), state=state,
                   total=len(rows), **counts, seconds=round(sum(r.get('seconds', 0) for r in rows), 2),
                   errors=[dict(image=r['image'], error=r.get('error', '')) for r in rows if r['status'] == 'error'],
                   warnings_by_image={r['image']: r['warnings'] for r in rows if r.get('warnings')})
    write_json(output / 'report.json', dict(schema_version=1, run_id=manifest['run_id'], updated_at=now(), images=rows))
    write_json(output / 'summary.json', summary)
    render_gallery(output, rows, manifest['run_id'])
    return summary


def stop_process(process):
    """Останавливается только дерево запущенной страницы, включая Windows venv launcher."""
    if os.name == 'nt':
        try:
            result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and process.poll() is None:
                raise OSError('Остановка дерева процесса запрещена')
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Убираем хотя бы непосредственный процесс, но не запускаем следующую страницу:
            # venv launcher мог оставить дочерний интерпретатор вне доступных прав.
            process.kill()
            process.wait()
            raise ProcessStopError('Не удалось остановить дерево страницы; очередь остановлена. Проверьте права процесса.') from exc
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def run_process(command, log, timeout, progress_prefix=None):
    options = dict(start_new_session=True) if os.name != 'nt' else dict(creationflags=subprocess.CREATE_NO_WINDOW)
    with subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING='utf-8'), **options) as process:
        started = last_output = time.monotonic()
        pending = b''
        current_stage = 'инициализация'
        with Path(log.name).open('rb') as reader:
            try:
                while True:
                    code = process.poll()
                    if progress_prefix:
                        pending += reader.read()
                        lines = pending.split(b'\n')
                        pending = lines.pop()
                        for line in lines:
                            text = line.decode('utf-8', errors='replace').strip()
                            if text.startswith(PROGRESS_MARKER):
                                try:
                                    status = json.loads(text[len(PROGRESS_MARKER):])
                                    current_stage = f'{status["stage"]}% {status["message"]}'
                                except (ValueError, KeyError, TypeError):
                                    continue
                                print(f'{progress_prefix} | {current_stage}', flush=True)
                                last_output = time.monotonic()
                        if code is None and time.monotonic() - last_output >= HEARTBEAT_SECONDS:
                            elapsed = int(time.monotonic() - started)
                            print(f'{progress_prefix} | {current_stage} | выполняется {elapsed} с', flush=True)
                            last_output = time.monotonic()
                    if code is not None:
                        return code
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        process.wait(timeout=min(0.25, remaining))
                    except subprocess.TimeoutExpired:
                        pass
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                stop_process(process)
                raise


def execute_page(output, manifest, row):
    folder = output / row['id']
    folder.mkdir(exist_ok=True)
    started = time.monotonic()
    record = folder / 'record.json'
    # Старый error не должен выдаваться за результат повторной попытки.
    write_json(record, dict(row, status='running'))
    try:
        with (folder / 'process.log').open('w', encoding='utf-8') as log:
            code = run_process([sys.executable, str(Path(__file__).resolve()), '_worker',
                                '--output', str(output), '--id', row['id']], log, manifest['options']['page_timeout'],
                               f'[{int(row["id"])}/{len(manifest["images"])}] {row["image"]}')
        result = read_json(record)
        if code or result.get('status') not in ('done', 'error'):
            return dict(row, status='error', seconds=round(time.monotonic() - started, 2),
                        error=f'Авария процесса (код {code}); см. process.log')
        return result
    except subprocess.TimeoutExpired:
        return dict(row, status='error', seconds=round(time.monotonic() - started, 2), error='Истёк предел времени страницы; см. process.log')
    except (OSError, ValueError) as exc:
        return dict(row, status='error', seconds=round(time.monotonic() - started, 2), error=str(exc))


def run_queue(output, manifest, retry_errors=False):
    rows = records(output, manifest)
    print(f'ПРОГОН: {len(rows)} изображений. Отчёты: {output}', flush=True)
    event(output, 'run_started')
    publish(output, manifest, rows, 'running')
    try:
        for index, row in enumerate(rows):
            if row['status'] == 'done' or (row['status'] == 'error' and not retry_errors):
                reason = 'готовый результат' if row['status'] == 'done' else 'ошибка; повтор — с --retry-errors'
                print(f'[{index + 1}/{len(rows)}] ПРОПУСК {row["image"]}: {reason}', flush=True)
                continue
            print(f'[{index + 1}/{len(rows)}] НАЧАЛО {row["image"]}', flush=True)
            event(output, 'page_started', id=row['id'], image=row['image'])
            rows[index] = dict(row, status='running')
            publish(output, manifest, rows, 'running')
            rows[index] = execute_page(output, manifest, row)
            write_json(output / row['id'] / 'record.json', rows[index])
            event(output, 'page_finished', id=row['id'], status=rows[index]['status'])
            publish(output, manifest, rows, 'running')
            result = rows[index]
            label = 'ГОТОВО' if result['status'] == 'done' else 'ОШИБКА'
            detail = result.get('error', f'предупреждений: {len(result.get("warnings", []))}')
            print(f'[{index + 1}/{len(rows)}] {label} {row["image"]} | {result.get("seconds", 0)} с | {detail}', flush=True)
    except ProcessStopError as exc:
        rows[index] = dict(rows[index], status='error', error=str(exc))
        write_json(output / rows[index]['id'] / 'record.json', rows[index])
        publish(output, manifest, rows, 'stop_failed')
        event(output, 'run_stopped', error=str(exc))
        print(f'ОСТАНОВЛЕНО: {exc}', flush=True)
        return 2
    except KeyboardInterrupt:
        # Незавершённая страница становится pending при следующем чтении, а не готовой.
        rows = [dict(r, status='pending') if r['status'] == 'running' else r for r in rows]
        publish(output, manifest, rows, 'interrupted')
        event(output, 'run_interrupted')
        print(f'ПРЕРВАНО. Отчёт: {output / "summary.json"}', flush=True)
        return 130
    failed = any(r['status'] != 'done' for r in rows)
    summary = publish(output, manifest, rows, 'completed_with_errors' if failed else 'completed')
    event(output, 'run_finished', state=summary['state'], done=summary['done'], error=summary['error'])
    print(f'ИТОГ: готово {summary["done"]}/{summary["total"]}, ошибок {summary["error"]}. Галерея: {output / "index.html"}', flush=True)
    return 1 if failed else 0


def worker(output, ident):
    from src.config import Config
    from src.page_pipeline import PagePipeline
    manifest = read_json(output / 'manifest.json')
    row = next(r for r in manifest['images'] if r['id'] == ident)
    folder = output / ident
    started = time.monotonic()
    try:
        if code_hashes() != manifest['code_hashes']:
            raise ValueError('Код изменился во время прогона')
        source = Path(row['source_path']) if row.get('source_path') else Path(manifest['input_root']) / row['image']
        if digest(source) != row['source_sha256']:
            raise ValueError('Исходник изменился во время прогона')
        config = Config(**manifest['config'], llm_api_key='')
        def progress(stage, message):
            print(PROGRESS_MARKER + json.dumps(dict(stage=stage, message=message), ensure_ascii=False), flush=True)
            event(output, 'page_progress', id=ident, stage=stage, message=message)
        result = PagePipeline(config).process(str(source), source_lang=config.source_lang,
                    target_lang=config.target_lang, debug_dir=folder / 'debug', progress_callback=progress)
        result.output_image.save(folder / 'result.png')
        write_json(folder / 'regions.json', result.regions_payload())
        row.update(status='done', regions=len(result.regions), ocr=result.ocr_engine,
                   translator=result.translator_engine, warnings=result.warnings,
                   result_sha256=digest(folder / 'result.png'))
    except Exception as exc:
        traceback.print_exc()
        row.update(status='error', error=str(exc))
    row['seconds'] = round(time.monotonic() - started, 2)
    write_json(folder / 'record.json', row)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Новый прогон или продолжение существующего')
    run.add_argument('--config', required=True, type=Path)
    run.add_argument('--images-root', type=Path, default=ROOT / 'test-img')
    run.add_argument('--output', type=Path, default=ROOT / 'output' / ('review-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    run.add_argument('--include', action='append', default=[], help='Glob относительно images-root; можно повторять')
    run.add_argument('--exclude', action='append', default=[])
    run.add_argument('--images', nargs='+', action='extend', default=[], help='Явные локальные пути; можно несколько и повторять опцию')
    run.add_argument('--list-file', type=Path, action='append', default=[], help='TXT (путь на строку) или JSON-массив путей; можно повторять')
    run.add_argument('--page-timeout', type=int, default=1800, help='Предел времени страницы в секундах')
    run.add_argument('--retry-errors', action='store_true')
    run.add_argument('--dry-run', action='store_true', help='Только состав и сервер; без записи и отправки')
    run.add_argument('--background', action='store_true', help='Запуск без ожидания; журнал в runner.log')
    for name in ('status', 'gallery'):
        command = commands.add_parser(name, help='Статус' if name == 'status' else 'Перестроить галерею без обработки')
        command.add_argument('--output', required=True, type=Path)
        if name == 'gallery':
            command.add_argument('--watch', action='store_true', help='Обновлять статус активного прогона без обработки')
            command.add_argument('--background', action='store_true', help='Наблюдать без ожидания, только с --watch')
    internal = commands.add_parser('_worker', help=argparse.SUPPRESS)
    internal.add_argument('--output', required=True, type=Path)
    internal.add_argument('--id', required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    args.output = args.output.resolve()
    try:
        if args.command == '_worker':
            worker(args.output, args.id)
            return 0
        if args.command == 'status':
            print(json.dumps(read_json(args.output / 'summary.json'), ensure_ascii=False, indent=2))
            return 0
        if args.command == 'gallery':
            if args.background and not args.watch:
                raise ValueError('--background для gallery требует --watch')
            if args.watch:
                if args.background:
                    command = [sys.executable, str(Path(__file__).resolve()), 'gallery',
                               '--output', str(args.output), '--watch']
                    options = dict(start_new_session=True) if os.name != 'nt' else dict(creationflags=subprocess.CREATE_NO_WINDOW)
                    with (args.output / 'gallery.log').open('a', encoding='utf-8') as log:
                        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, **options)
                    print(json.dumps(dict(pid=process.pid, gallery=str(args.output / 'index.html'))))
                    return 0
                return watch_gallery(args.output)
            with run_lock(args.output):
                report = read_json(args.output / 'report.json')
                rows = report if isinstance(report, list) else report['images']
                run_id = args.output.name if isinstance(report, list) else report['run_id']
                render_gallery(args.output, rows, run_id)
            print(args.output / 'index.html')
            return 0
        if args.page_timeout <= 0:
            raise ValueError('--page-timeout должен быть положительным')
        current = prepare(args)
        saved_path = args.output / 'manifest.json'
        if saved_path.exists():
            saved = read_json(saved_path)
            if not isinstance(saved, dict):
                raise ValueError('Старый формат прогона: используйте новый --output; gallery поддерживает старый отчёт')
            validate_resume(saved, current)
            current = saved
        if args.dry_run:
            print(json.dumps(dict(total=len(current['images']), images=current['images'],
                                 server=current['config']['llm_base_url'], api_key_used=False,
                                 output=str(args.output)), ensure_ascii=False, indent=2))
            return 0
        args.output.mkdir(parents=True, exist_ok=True)
        with run_lock(args.output):
            if not saved_path.exists():
                if any(p.name != '.run.lock' for p in args.output.iterdir()):
                    raise ValueError('Для нового прогона нужен пустой каталог --output')
                write_json(saved_path, current)
            else:
                validate_resume(read_json(saved_path), current)
            if not args.background:
                return run_queue(args.output, current, args.retry_errors)
            publish(args.output, current, records(args.output, current), 'queued')
            if current['options']['selection'] == 'explicit':
                write_json(args.output / 'selected-inputs.json', [row['source_path'] for row in current['images']])
        command = [sys.executable, str(Path(__file__).resolve()), 'run', '--config', str(args.config.resolve()),
                   '--images-root', str(args.images_root.resolve()), '--output', str(args.output),
                   '--page-timeout', str(args.page_timeout)]
        for option in ('include', 'exclude'):
            for value in getattr(args, option):
                command.extend(['--' + option, value])
        if current['options']['selection'] == 'explicit':
            command.extend(['--list-file', str(args.output / 'selected-inputs.json')])
        if args.retry_errors:
            command.append('--retry-errors')
        options = dict(start_new_session=True) if os.name != 'nt' else dict(creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        with (args.output / 'runner.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING='utf-8'), **options)
        print(json.dumps(dict(pid=process.pid, gallery=str(args.output / 'index.html'),
                              log=str(args.output / 'runner.log')), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    # Единая кодировка консоли и перенаправленных журналов, включая русский текст и пути.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    raise SystemExit(main())
