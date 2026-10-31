"""Обновить примеры README через основной пайплайн, сохранив происхождение результата."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
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


def render(case: dict, manifest: dict, pipeline, model: str) -> None:
    """Один сквозной запуск без ручной правки OCR, масок, перевода или вёрстки."""
    name = case["id"]
    work = ROOT / "output/readme-examples" / name
    work.mkdir(parents=True, exist_ok=True)
    input_path = work / "input.png"
    prepared_image(case).save(input_path)
    started = time.perf_counter()
    result = pipeline.process(str(input_path), source_lang=case["source_lang"],
                              target_lang=case["target_lang"], debug_dir=work / "debug")
    translated = EXAMPLES / "translated" / (name + ".png")
    translated.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(translated))
    payload = result.regions_payload()
    payload["source_path"] = case["input"]
    write_json(EXAMPLES / "regions" / (name + ".json"), payload)
    compose(case)
    artifacts = [f"translated/{name}.png", f"regions/{name}.json",
                 f"comparisons/{name}.jpg", f"comparisons/{name}-full.jpg"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": git_revision(), "python": platform.python_version(), "platform": platform.system(),
        "model": model, "source_lang": case["source_lang"], "target_lang": case["target_lang"],
        "input_sha256": case["sha256"], "crop": case.get("crop"),
        "prepared_input_sha256": digest(input_path), "settings": manifest["settings"],
        "seconds": round(time.perf_counter() - started, 2),
        "ocr_engine": result.ocr_engine, "translator_engine": result.translator_engine,
        "regions": len(result.regions), "warnings": result.warnings,
        "stages_completed": result.stages_completed, "timings": result.timings,
        "fonts": sorted({region.style.font_id for region in result.regions if region.style.font_id}),
        "manual_edits": False, "artifacts": {path: digest(EXAMPLES / path) for path in artifacts},
    }
    write_json(EXAMPLES / "runs" / (name + ".json"), report)
    print(f"DONE {name}: {report['regions']} regions, {report['seconds']}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true", help="Повторить OCR, перевод, LaMa и вёрстку")
    mode.add_argument("--verify", action="store_true", help="Проверить хеши без моделей и сети")
    parser.add_argument("--case", choices=("chinese", "korean", "japanese", "english"))
    parser.add_argument("--llm-url", default=os.environ.get("ILT_LLM_URL", ""))
    parser.add_argument("--llm-model", default=os.environ.get("ILT_LLM_MODEL", ""))
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models")
    args = parser.parse_args()
    manifest = json.loads((EXAMPLES / "manifest.json").read_text("utf-8"))
    cases = [case for case in manifest["cases"] if not args.case or case["id"] == args.case]
    verify_sources(cases)
    if args.verify:
        verify_outputs(cases, manifest)
        return
    if not args.llm_url:
        parser.error("Укажите --llm-url или ILT_LLM_URL; адрес и ключ не сохраняются в отчётах")
    from src.config import Config
    from src.page_pipeline import PagePipeline
    from src.utils.llm_client import LlmClient

    key = os.environ.get("ILT_LLM_API_KEY", "")
    client = LlmClient(args.llm_url, model=args.llm_model, api_key=key)
    model = client.resolve_model()
    config = Config(**manifest["settings"], llm_base_url=args.llm_url, llm_model=model,
                    llm_api_key=key, models_dir=str(args.models_dir.resolve()))
    pipeline = PagePipeline(config)
    # LLM обслуживает только один запрос за раз.
    for case in cases:
        print(f"START {case['id']}", flush=True)
        render(case, manifest, pipeline, model)
    verify_outputs(cases, manifest)


if __name__ == "__main__":
    main()
