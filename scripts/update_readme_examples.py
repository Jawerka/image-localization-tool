"""Обновить примеры README через основной пайплайн, сохранив происхождение результата."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import shutil
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples"
sys.path.insert(0, str(ROOT))


def digest(path: Path) -> str:
    """Контрольная сумма файла без преобразования изображения."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    """Сохранить читаемый отчёт в UTF-8."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def prepared_image(case: dict) -> Image.Image:
    """Применить только заранее зафиксированную обрезку длинной ленты."""
    with Image.open(EXAMPLES / case["input"]) as source:
        image = source.convert("RGB")
    if case.get("crop"):
        image = image.crop(tuple(case["crop"]))
    return image


def label_font(size: int):
    """Внешние подписи сравнения; шрифт переводов выбирает сама программа."""
    return ImageFont.truetype(str(ROOT / "src/resources/fonts/Heroika-Regular.otf"), size)


def compose(case: dict) -> None:
    """Слева исходник, справа неизменённый вывод программы; подписи вне рисунка."""
    original = prepared_image(case)
    with Image.open(EXAMPLES / "translated" / (case["id"] + ".png")) as source:
        translated = source.convert("RGB")
    if translated.size != original.size:
        raise ValueError(f"Размер результата изменился: {case['id']}")
    # Полное сравнение сохраняет исходные пиксели; README использует уменьшенную копию.
    width, height = original.size
    header, footer, gap = 90, 95, 24
    canvas = Image.new("RGB", (width * 2 + gap, height + header + footer), "#f2f3f5")
    canvas.paste(original, (0, header))
    canvas.paste(translated, (width + gap, header))
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), f"Original / {case['source_lang']}", font=label_font(28), fill="#202631")
    draw.text((width + gap + 18, 18), "Automatic translation / ru", font=label_font(28), fill="#202631")
    # Указание авторства остаётся вместе с изображением при скачивании.
    credit = case["credit"]
    font = label_font(18)
    words, lines, line = credit.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=font) > canvas.width - 36 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    for index, line in enumerate(lines):
        draw.text((18, header + height + 8 + index * 22), line, font=font, fill="#202631")
    draw.text((18, canvas.height - 28), "Russian adaptation: Image Localization Tool. No manual retouching.",
              font=font, fill="#202631")
    folder = EXAMPLES / "comparisons"
    folder.mkdir(parents=True, exist_ok=True)
    canvas.save(folder / (case["id"] + "-full.jpg"), quality=95, subsampling=0)
    if canvas.width > 1600:
        canvas = canvas.resize((1600, round(canvas.height * 1600 / canvas.width)), Image.Resampling.LANCZOS)
    canvas.save(folder / (case["id"] + ".jpg"), quality=90, subsampling=0)


def verify_sources(cases: list[dict]) -> None:
    """Не подменять эталоны незаметно при будущих запусках."""
    for case in cases:
        path = EXAMPLES / case["input"]
        if digest(path) != case["sha256"]:
            raise ValueError(f"Изменился оригинал: {case['id']}")
        with Image.open(path) as image:
            image.verify()


def verify_outputs(cases: list[dict], manifest: dict) -> None:
    """Проверить связи результата с входом, настройками и файлами сравнения."""
    for case in cases:
        name = case["id"]
        report = json.loads((EXAMPLES / "runs" / (name + ".json")).read_text("utf-8"))
        if report["input_sha256"] != case["sha256"] or report["crop"] != case.get("crop"):
            raise ValueError(f"Результат сделан из другого исходника: {name}")
        if report["settings"] != manifest["settings"]:
            raise ValueError(f"Настройки результата устарели: {name}")
        if report["source_lang"] != case["source_lang"] or report["target_lang"] != case["target_lang"]:
            raise ValueError(f"Не совпадает направление перевода: {name}")
        for relative, expected in report["artifacts"].items():
            if digest(EXAMPLES / relative) != expected:
                raise ValueError(f"Изменился артефакт: {relative}")
        print(f"OK {name}: {report['regions']} regions, {len(report['warnings'])} warnings")


def git_revision() -> dict:
    """Зафиксировать код и незакоммиченные изменения, включая генератор."""
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # Публичные картинки сами по себе не меняют исполняемый код.
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", "src", "scripts/update_readme_examples.py"], cwd=ROOT)
    return {"commit": revision, "tracked_code_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "tracked_code_dirty": bool(diff), "generator_sha256": digest(Path(__file__))}


def prepare_run(folder: Path, cases: list[dict], manifest: dict, config_path: Path) -> None:
    """Подготовить фиксированные входы для общей очереди test_images.py."""
    from src.config import Config
    if not config_path.is_file():
        raise ValueError(f'Нужен существующий файл настроек: {config_path}')
    installed = Config.load(config_path)
    config = Config(**manifest['settings'], source_lang='auto', target_lang='ru',
                    llm_base_url=installed.llm_base_url, llm_model=installed.llm_model,
                    models_dir=installed.models_dir, llm_api_key='')
    if folder.exists():
        raise ValueError(f'Для нового прогона нужна новая папка: {folder}')
    (folder / 'inputs').mkdir(parents=True)
    for case in cases:
        prepared_image(case).save(folder / 'inputs' / (case['id'] + '.png'))
    write_json(folder / 'config.json', {k: str(v) if isinstance(v, Path) else v
                                      for k, v in asdict(config).items() if not k.startswith('_')})
    write_json(folder / 'preparation.json', dict(code=git_revision(), cases=[c['id'] for c in cases]))


def import_run(folder: Path, cases: list[dict], manifest: dict) -> None:
    """Опубликовать неизменённые результаты общей очереди и их происхождение."""
    run = json.loads((folder / 'run' / 'manifest.json').read_text('utf-8'))
    summary = json.loads((folder / 'run' / 'summary.json').read_text('utf-8'))
    if summary['state'] not in ('completed', 'completed_with_errors'):
        raise ValueError('Дождитесь завершения очереди')
    preparation = json.loads((folder / 'preparation.json').read_text('utf-8'))
    rows = json.loads((folder / 'run' / 'report.json').read_text('utf-8'))['images']
    if any(run['config'].get(k) != v for k, v in manifest['settings'].items()):
        raise ValueError('Настройки очереди отличаются от манифеста примеров')
    ready = []
    for case in cases:
        name = case['id']
        row = next(r for r in rows if r['image'] == name + '.png')
        if row['status'] != 'done':
            raise ValueError(f'Пример не завершён: {name}')
        source = folder / 'inputs' / (name + '.png')
        if digest(source) != row['source_sha256']:
            raise ValueError(f'Вход изменился после запуска: {name}')
        with Image.open(source) as image:
            expected = prepared_image(case)
            if image.size != expected.size or image.convert('RGB').tobytes() != expected.tobytes():
                raise ValueError(f'Вход не соответствует публичному манифесту: {name}')
        page = folder / 'run' / row['id']
        if digest(page / 'result.png') != row['result_sha256']:
            raise ValueError(f'Результат изменился: {name}')
        with Image.open(page / 'result.png') as result:
            if result.size != expected.size:
                raise ValueError(f'Размер результата изменился: {name}')
        payload = json.loads((page / 'regions.json').read_text('utf-8'))
        ready.append((case, row, page, payload))
    # Проверить весь набор до первой замены публичных артефактов.
    for case, row, page, payload in ready:
        name = case['id']
        target = EXAMPLES / 'translated' / (name + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(page / 'result.png', target)
        payload['source_path'] = case['input']
        write_json(EXAMPLES / 'regions' / (name + '.json'), payload)
        compose(case)
        artifacts = [f'translated/{name}.png', f'regions/{name}.json',
                     f'comparisons/{name}.jpg', f'comparisons/{name}-full.jpg']
        report = dict(generated_at=summary['updated_at'], code=preparation['code'],
                      python=platform.python_version(), platform=platform.system(),
                      model=run['config']['llm_model'], source_lang=case['source_lang'], target_lang='ru',
                      effective_source_lang=run['config']['source_lang'], run_id=run['run_id'],
                      input_sha256=case['sha256'], crop=case.get('crop'),
                      prepared_input_sha256=row['source_sha256'], settings=manifest['settings'],
                      seconds=row['seconds'], ocr_engine=row['ocr'], translator_engine=row['translator'],
                      regions=row['regions'], warnings=row['warnings'], timings=payload.get('timings', {}),
                      fonts=sorted({r['style']['font_id'] for r in payload['regions'] if r['style']['font_id']}),
                      manual_edits=False, artifacts={p: digest(EXAMPLES / p) for p in artifacts})
        write_json(EXAMPLES / 'runs' / (name + '.json'), report)
    verify_outputs(cases, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true", help="Устаревший вход: выводит инструкцию перехода")
    mode.add_argument("--verify", action="store_true", help="Проверить хеши без моделей и сети")
    mode.add_argument('--prepare-run', type=Path, help='Подготовить входы стандартной очереди')
    mode.add_argument('--import-run', type=Path, help='Перенести готовые результаты стандартной очереди')
    parser.add_argument('--config', type=Path, help='Настройки сервера для подготовки очереди')
    parser.add_argument("--case", choices=("chinese", "korean", "japanese", "english"))
    args = parser.parse_args()
    manifest = json.loads((EXAMPLES / "manifest.json").read_text("utf-8"))
    cases = [case for case in manifest["cases"] if not args.case or case["id"] == args.case]
    verify_sources(cases)
    if args.prepare_run:
        if not args.config:
            parser.error('--prepare-run требует --config')
        prepare_run(args.prepare_run.resolve(), cases, manifest, args.config)
        return
    if args.import_run:
        import_run(args.import_run.resolve(), cases, manifest)
        return
    if args.verify:
        verify_outputs(cases, manifest)
        return
    parser.error('--render заменён общей очередью: используйте --prepare-run, '
                 'scripts/test_images.py run и --import-run; см. docs/examples/README.md')


if __name__ == "__main__":
    main()
