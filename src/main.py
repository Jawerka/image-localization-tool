"""Image Localization Tool - CLI интерфейс."""

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config import Config
from src.utils.logger import enable_file_logging, logger

enable_file_logging("app.log")
from src.app.ingest import list_images
from src.utils.paths import get_output_path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def print_progress(progress: int, status: str):
    """Выводить прогресс в консоль."""
    print(f"\r[{progress:3d}%] {status}", end="", flush=True)
    if progress == 100:
        print()


def collect_inputs(path: Path) -> list[Path]:
    """Файл или папка изображений. Companion-маски пропускаются."""
    if path.is_dir():
        files = []
        for item in sorted(path.iterdir()):
            if not item.is_file() or item.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if "-mask" in item.stem:
                continue
            files.append(item)
        return files
    return [path]


def write_regions(result, output_path: Path) -> Path:
    """Сохранить regions.json рядом с результатом."""
    path = output_path.with_suffix(".regions.json")
    path.write_text(
        json.dumps(result.regions_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    """Создать парсер аргументов CLI."""
    parser = argparse.ArgumentParser(
        description="Оффлайн-переводчик текста на изображениях"
    )
    parser.add_argument(
        "input",
        type=str,
        nargs="?",
        help="Путь к изображению или папке",
    )
    parser.add_argument(
        "output",
        type=str,
        nargs="?",
        default=None,
        help="Путь к выходному изображению (опционально)",
    )
    parser.add_argument(
        "--target-lang",
        type=str,
        default="ru",
        help="Язык перевода (ISO 639-1, по умолчанию: ru)",
    )
    parser.add_argument("--config", type=str, default=None, help="Путь к config.json")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Минимальная уверенность OCR (0.0-1.0)",
    )
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод")
    parser.add_argument("--source-lang", type=str, default=None, help="Язык оригинала, ISO 639-1")
    parser.add_argument("--llm-url", type=str, default=None, help="OpenAI-совместимый URL LLM")
    parser.add_argument("--llm-think", action="store_true", help="Включить thinking на сервере LLM")
    parser.add_argument("--ocr", choices=["vlm", "rapid"], default=None, help="OCR: vlm или rapid")
    parser.add_argument(
        "--translator",
        choices=["llm", "argos"],
        default=None,
        help="Переводчик: llm или argos",
    )
    parser.add_argument(
        "--inpainter",
        choices=["lama", "opencv"],
        default=None,
        help="Очистка: lama или opencv",
    )
    parser.add_argument(
        "--reading-order",
        choices=["auto", "ltr", "rtl"],
        default=None,
        help="Порядок чтения. auto — решает VLM, геометрия только как фолбэк",
    )
    parser.add_argument("--translate-sfx", action="store_true", help="Переводить звуковые эффекты")
    parser.add_argument("--glossary", type=str, default=None, help="Файл глоссария имён")
    parser.add_argument("--debug-dir", type=str, default=None, help="Папка промежуточных картинок")
    parser.add_argument(
        "--rerender",
        type=str,
        default=None,
        help="Папка или regions.json: перевёрстка без повторного OCR",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Для папки: брать изображения во вложенных каталогах",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Для папки: не обрабатывать страницу, если файл перевода уже есть",
    )
    return parser


def apply_v2_config(args, config: Config) -> None:
    """Перенести флаги CLI в Config."""
    if args.llm_url:
        config.llm_base_url = args.llm_url
    if args.llm_think:
        config.llm_thinking = True
    if args.ocr:
        config.ocr_backend = args.ocr
    if args.translator:
        config.translator_backend = args.translator
    if args.inpainter:
        config.inpainter_backend = args.inpainter
    if args.reading_order:
        config.reading_order = args.reading_order
    if args.translate_sfx:
        config.translate_sfx = True
        config.sfx_mode = "replace"
    if args.glossary:
        config.glossary_path = args.glossary
    if args.min_confidence is not None:
        config.min_confidence = args.min_confidence


def source_language(args, config: Config) -> str:
    if args.source_lang:
        return args.source_lang
    return config.source_lang


def plan_batch_io(
    input_path: Path,
    output: str | Path | None = None,
    *,
    recursive: bool = False,
    skip_existing: bool = False,
) -> dict:
    """Список файлов папки и каркас отчёта. Модели не загружает.

    Папка обходится ``list_images``: естественный порядок, ``page2`` раньше
    ``page10``. ``recursive`` включает вложенные каталоги. Файлы со ``-mask``
    в stem пропускаются. ``skip_existing`` откладывает страницу, если
    ``<stem>_translated<suffix>`` уже лежит в каталоге выхода.

    Ключи: ``output_dir``, ``pages``, ``errors``, ``skipped``.
    У страницы и пропуска есть ``source``, ``destination`` и ``name``.
    У пропуска ещё ``reason`` (``уже есть``). ``errors`` пустой — его
    заполняет прогон.
    """
    root = Path(input_path)
    out_dir = Path(output) if output else Path("output") / "v2"
    pages: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    if not root.exists():
        errors.append({"source": str(root), "reason": "не найден"})
        files: list[Path] = []
    elif root.is_dir():
        files = [
            path
            for path in list_images(root, recursive)
            if "-mask" not in path.stem.lower()
        ]
    elif root.is_file() and root.suffix.lower() in IMAGE_SUFFIXES and "-mask" not in root.stem.lower():
        files = [root]
    else:
        files = []
    for source in files:
        destination = out_dir / f"{source.stem}_translated{source.suffix}"
        record = {
            "source": str(source),
            "destination": str(destination),
            "name": source.name,
        }
        if skip_existing and destination.is_file():
            skipped.append({**record, "reason": "уже есть"})
            continue
        pages.append(record)
    return {
        "output_dir": str(out_dir),
        "pages": pages,
        "errors": errors,
        "skipped": skipped,
    }


def write_batch_report(report: dict, output_dir: Path | None = None) -> Path:
    """Записать ``report.json``: pages, errors, skipped."""
    directory = Path(output_dir) if output_dir is not None else Path(report.get("output_dir") or ".")
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "pages": list(report.get("pages") or []),
        "errors": list(report.get("errors") or []),
        "skipped": list(report.get("skipped") or []),
    }
    path = directory / "report.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def output_path_for(source: Path, output: str | None, many: bool) -> Path:
    if many:
        directory = Path(output) if output else Path("output") / "v2"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{source.stem}_translated{source.suffix}"
    if output:
        return Path(output)
    return Path(get_output_path(str(source)))


def find_regions_file(path: Path) -> Path:
    if path.is_file():
        return path
    direct = path / "regions.json"
    if direct.exists():
        return direct
    found = sorted(path.glob("*.regions.json"))
    if not found:
        raise FileNotFoundError(f"В {path} нет regions.json")
    return found[0]


def run_v2(args, config: Config) -> int:
    """Пайплайн v2. При недоступном LLM сам уходит на RapidOCR + Argos."""
    from src.page_pipeline import PagePipeline

    apply_v2_config(args, config)
    pipeline = PagePipeline(config)

    if args.rerender:
        regions_file = find_regions_file(Path(args.rerender))
        output = Path(args.output) if args.output else regions_file.with_name("rerender.png")
        print("Image Localization Tool — перевёрстка")
        print(f"Регионы: {regions_file}")
        print(f"Выход: {output}")
        try:
            result = pipeline.rerender(regions_file, debug_dir=args.debug_dir)
            output.parent.mkdir(parents=True, exist_ok=True)
            result.save(str(output))
            saved = write_regions(result, output)
        except Exception as exc:
            print(f"Ошибка перевёрстки: {exc}")
            logger.exception("Rerender failed")
            return 1
        print(f"Сохранено: {output}")
        print(f"Регионы: {saved}")
        return 0

    if not args.input:
        print("Ошибка: укажите входное изображение или папку")
        return 1
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Ошибка: Файл не найден: {input_path}")
        return 1

    plan = None
    dest_by_source: dict[str, Path] = {}
    if input_path.is_dir():
        if args.output and Path(args.output).suffix.lower() in IMAGE_SUFFIXES:
            print("Ошибка: для папки укажите каталог выхода, а не файл")
            return 1
        plan = plan_batch_io(
            input_path,
            args.output,
            recursive=bool(args.recursive),
            skip_existing=bool(args.skip_existing),
        )
        if not plan["pages"] and not plan["skipped"]:
            print(f"Ошибка: в {input_path} нет изображений")
            write_batch_report(plan, Path(plan["output_dir"]))
            return 1
        sources = [Path(item["source"]) for item in plan["pages"]]
        dest_by_source = {
            str(Path(item["source"]).resolve()): Path(item["destination"])
            for item in plan["pages"]
        }
        many = True
        if plan["skipped"]:
            print(f"Пропущено (уже есть): {len(plan['skipped'])}")
    else:
        sources = collect_inputs(input_path)
        if not sources:
            print(f"Ошибка: в {input_path} нет изображений")
            return 1
        many = len(sources) > 1
        if many and args.output and Path(args.output).suffix.lower() in IMAGE_SUFFIXES:
            print("Ошибка: для папки укажите каталог выхода, а не файл")
            return 1

    source_lang = source_language(args, config)
    print("Image Localization Tool")
    print("=======================")
    print(f"Вход: {input_path}")
    print(f"Языки: {source_lang} → {args.target_lang}")
    print(f"LLM: {config.llm_base_url}")
    print()

    exit_code = 0
    for source in sources:
        if plan is not None:
            destination = dest_by_source[str(source.resolve())]
        else:
            destination = output_path_for(source, args.output, many)
        debug_dir = None
        if args.debug_dir:
            debug_dir = Path(args.debug_dir) if len(sources) == 1 else Path(args.debug_dir) / source.stem
        print(f"Страница: {source.name} → {destination}")
        try:
            result = pipeline.process(
                str(source),
                source_lang=source_lang,
                target_lang=args.target_lang,
                progress_callback=print_progress,
                debug_dir=debug_dir,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            result.save(str(destination))
            regions_path = write_regions(result, destination)
        except Exception as exc:
            print(f"\nОшибка обработки: {exc}")
            logger.exception("Pipeline failed")
            exit_code = 1
            if plan is not None:
                plan["errors"].append({"source": str(source), "reason": str(exc)})
                failed = str(source.resolve())
                plan["pages"] = [
                    item
                    for item in plan["pages"]
                    if str(Path(item["source"]).resolve()) != failed
                ]
            continue

        print()
        print(f"  Этапы: {', '.join(result.stages_completed)}")
        print(f"  OCR: {result.ocr_engine}, перевод: {result.translator_engine}")
        print(f"  Регионов: {len(result.regions)}")
        print(f"  Файл регионов: {regions_path}")
        translated = [region for region in result.regions if region.translation]
        if translated:
            print("  Переводы:")
            for region in sorted(translated, key=lambda item: item.order):
                speaker = f" ({region.speaker})" if region.speaker else ""
                print(f'    [{region.block_type}] "{region.text}" → "{region.translation}"{speaker}')
        if result.warnings:
            print("  Предупреждения:")
            for warning in result.warnings:
                print(f"    ! {warning}")
        print()
    if plan is not None:
        write_batch_report(plan, Path(plan["output_dir"]))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.input is None and not args.rerender:
        parser.error("укажите входное изображение или папку")
    config = Config.load(args.config)
    return run_v2(args, config)


if __name__ == "__main__":
    sys.exit(main())
