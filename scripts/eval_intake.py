#!/usr/bin/env python3
"""Приёмка страниц: полный v2 строит маску, эталон открывается только после."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_pipeline import _MASK_NAME, find_pairs, page_quality
from src.app.ingest import is_image, natural_sort_key
from src.config import Config
from src.page_pipeline import PagePipeline
from src.utils.mask_metrics import load_perfect_mask_array

SKIP_DIR_NAMES = frozenset({"html"})


def is_companion_mask(path: Path) -> bool:
    """Компаньон эталона, не страница."""
    return _MASK_NAME.match(path.stem) is not None


def list_intake_pages(root: Path) -> list[Path]:
    """Исходники в корне и sound-ref без эталонов, html и миниатюр-дублей."""
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or not is_image(path):
            continue
        relative = path.relative_to(root)
        if any(part.casefold() in SKIP_DIR_NAMES for part in relative.parts[:-1]):
            continue
        if is_companion_mask(path):
            continue
        found.append(path)
    by_key: dict[tuple[Path, str], list[Path]] = {}
    for path in found:
        by_key.setdefault((path.parent, path.stem), []).append(path)
    pages: list[Path] = []
    for files in by_key.values():
        if len(files) == 1:
            pages.append(files[0])
            continue
        pngs = [item for item in files if item.suffix.lower() == ".png"]
        pages.append(max(pngs or files, key=lambda item: item.stat().st_size))
    pages.sort(key=lambda path: natural_sort_key(path.relative_to(root).as_posix()))
    return pages


def annotation_index(root: Path) -> dict[Path, tuple[Path, Path | None]]:
    """Эталон и зона баллона по абсолютному пути исходника."""
    index = {}
    for image, mask, zone in find_pairs(root):
        index[image.resolve()] = (mask, zone)
    return index


def _folder_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    if relative.parent == Path("."):
        return path.stem
    return str(relative.with_suffix("")).replace("\\", "/")


def _min_font(regions) -> int | None:
    sizes = [
        int(region.style.font_size)
        for region in regions
        if region.translation.strip() and not region.skip
    ]
    return min(sizes) if sizes else None


def _draw_markup(original: Image.Image, regions) -> Image.Image:
    marked = original.convert("RGB").copy()
    draw = ImageDraw.Draw(marked)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    for region in regions:
        x, y, w, h = [int(v) for v in region.bbox]
        color = (220, 40, 40) if region.bubble_bbox is not None else (40, 90, 220)
        draw.rectangle([x, y, x + w, y + h], outline=color, width=4)
        label = str(region.id)
        box = draw.textbbox((x, y), label, font=font)
        draw.rectangle(box, fill=color)
        draw.text((x, y), label, fill=(255, 255, 255), font=font)
    return marked


def _comparison(original: Image.Image, result: Image.Image) -> Image.Image:
    height = max(original.height, result.height)
    left = original.convert("RGB")
    right = result.convert("RGB")
    if left.height != height:
        scale = height / left.height
        left = left.resize((max(1, int(left.width * scale)), height))
    if right.height != height:
        scale = height / right.height
        right = right.resize((max(1, int(right.width * scale)), height))
    canvas = Image.new("RGB", (left.width + right.width, height), (240, 240, 240))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width, 0))
    return canvas


def _escape(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_html(out: Path, pages: list[dict]) -> None:
    """Столбик итоговых PNG со звёздами. Подпись человека в файл не пишется."""
    toc = []
    articles = []
    for page in pages:
        stem = page["stem"]
        folder = page["folder"]
        eval_row = page.get("eval") or {}
        recall = eval_row.get("ink_recall")
        recall_text = "нет эталона" if recall is None else f"recall {recall}"
        toc.append(f"<a href='#p-{_escape(stem)}'>{_escape(stem)}</a>")
        body = [
            f"<article id='p-{_escape(stem)}' data-stem='{_escape(stem)}'>",
            f"<h2>{_escape(stem)}</h2>",
            f"<p class='meta'>{_escape(page.get('ocr_engine') or '')} / "
            f"{_escape(page.get('translator_engine') or '')}, "
            f"регионов {page.get('regions', 0)}, overflow {_escape(page.get('overflow'))}, "
            f"мин. кегль {_escape(page.get('min_font'))}, {recall_text}, "
            f"{_escape(page.get('seconds'))}s</p>",
        ]
        if page.get("error"):
            body.append(f"<p>ошибка: {_escape(page['error'])}</p>")
        else:
            body.append(
                f"<a href='{_escape(folder)}/result.png'>"
                f"<img loading='lazy' src='{_escape(folder)}/result.png' "
                f"alt='{_escape(stem)} результат'></a>"
            )
            body.append(
                "<details><summary>Исходник и сравнение</summary>"
                f"<img loading='lazy' src='{_escape(folder)}/comparison.jpg' "
                f"alt='{_escape(stem)} сравнение'>"
                "</details>"
            )
            body.append(
                f"<p><a href='{_escape(folder)}/markup.jpg'>разметка</a> · "
                f"<a href='{_escape(folder)}/result.png'>результат</a> · "
                f"<a href='{_escape(folder)}/clean.png'>очистка</a> · "
                f"<a href='{_escape(folder)}/mask.png'>маска</a></p>"
            )
        body.append(
            "<div class='rate'>"
            "<p class='stars' aria-label='оценка'>"
            + "".join(
                f"<button type='button' data-star='{n}' title='{n}'>★</button>"
                for n in range(1, 6)
            )
            + "</p>"
            "<p class='verdict'>"
            "<button type='button' data-verdict='accepted'>принято</button>"
            "<button type='button' data-verdict='deferred'>отложено</button>"
            "<button type='button' data-verdict='rejected'>отклонено</button>"
            "<button type='button' data-verdict=''>сбросить</button>"
            "</p>"
            "<textarea rows='2' placeholder='Заметка (локально в браузере)'></textarea>"
            "</div></article>"
        )
        articles.append("".join(body))
    storage_key = f"ilt-intake-stars:{out.name}"
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Приёмка — { _escape(out.name) }</title>
<style>
body{{font:16px/1.45 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#e8e8ea;background:#121214}}
img{{max-width:100%;height:auto;background:#1c1c1e;display:block}}
article{{margin:0 0 56px;padding-bottom:28px;border-bottom:1px solid #2c2c32}}
.meta,.toc{{color:#9a9aa3}}
.toc{{display:flex;flex-wrap:wrap;gap:8px 14px;margin:12px 0 28px}}
a{{color:#8cb4ff}}
.stars button{{font-size:32px;line-height:1;background:none;border:0;cursor:pointer;color:#5c5c64;padding:0 2px}}
.stars button.on{{color:#e2a100}}
.verdict button{{margin:0 6px 8px 0;padding:6px 10px;background:#1c1c20;color:#e8e8ea;border:1px solid #3a3a42}}
.verdict button.on{{background:#29453d;color:#fff;border-color:#29453d}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#1c1c20;color:#e8e8ea;border:1px solid #3a3a42}}
details{{margin:12px 0}}
#dump{{width:100%;min-height:8em;margin-top:8px;background:#1c1c20;color:#e8e8ea;border:1px solid #3a3a42}}
</style>
<h1>Обработанные тестовые страницы</h1>
<p class="meta">Столбик итоговых PNG. Звёзды и вердикт сохраняются в этом браузере, не в acceptance.json.
Автомаска из v2; эталон только в числах. {len(pages)} страниц, статус прогона: pending.</p>
<p class="toc">{"".join(toc)}</p>
{"".join(articles)}
<p><button type="button" id="copy">Скопировать оценки JSON</button></p>
<textarea id="dump" readonly></textarea>
<script>
const KEY = {json.dumps(storage_key)};
const load = () => {{ try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch {{ return {{}}; }} }};
const save = (data) => localStorage.setItem(KEY, JSON.stringify(data));
const dump = () => {{ document.getElementById("dump").value = JSON.stringify(load(), null, 2); }};
function paint(article, rec) {{
  rec = rec || {{}};
  article.querySelectorAll(".stars button").forEach((btn) => {{
    btn.classList.toggle("on", Number(rec.stars || 0) >= Number(btn.dataset.star));
  }});
  article.querySelectorAll(".verdict button").forEach((btn) => {{
    btn.classList.toggle("on", (rec.verdict || "") === btn.dataset.verdict && btn.dataset.verdict !== "");
  }});
  const note = article.querySelector("textarea");
  if (note && document.activeElement !== note) note.value = rec.note || "";
}}
const data = load();
document.querySelectorAll("article[data-stem]").forEach((article) => {{
  const stem = article.dataset.stem;
  paint(article, data[stem]);
  article.querySelectorAll(".stars button").forEach((btn) => {{
    btn.addEventListener("click", () => {{
      const all = load();
      all[stem] = Object.assign({{stars: 0, verdict: "", note: ""}}, all[stem], {{stars: Number(btn.dataset.star)}});
      save(all); paint(article, all[stem]); dump();
    }});
  }});
  article.querySelectorAll(".verdict button").forEach((btn) => {{
    btn.addEventListener("click", () => {{
      const all = load();
      all[stem] = Object.assign({{stars: 0, verdict: "", note: ""}}, all[stem], {{verdict: btn.dataset.verdict}});
      save(all); paint(article, all[stem]); dump();
    }});
  }});
  const note = article.querySelector("textarea");
  if (note) note.addEventListener("input", () => {{
    const all = load();
    all[stem] = Object.assign({{stars: 0, verdict: "", note: ""}}, all[stem], {{note: note.value}});
    save(all); dump();
  }});
}});
dump();
document.getElementById("copy").addEventListener("click", async () => {{
  dump();
  try {{ await navigator.clipboard.writeText(document.getElementById("dump").value); }} catch {{}}
}});
</script>
"""
    (out / "index.html").write_text(html, encoding="utf-8")


def process_page(
    pipeline: PagePipeline,
    source: Path,
    root: Path,
    out: Path,
    annotation: tuple[Path, Path | None] | None,
) -> dict:
    """Полный прогон одной страницы; эталон читается после очистки."""
    folder = _folder_name(source, root)
    destination = out / folder
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / f"original{source.suffix.lower()}")
    result = pipeline.process(str(source), debug_dir=destination / "debug")
    original = Image.open(source).convert("RGB")
    result.output_image.save(destination / "result.png")
    debug = destination / "debug"
    auto_mask = np.zeros((original.height, original.width), dtype=np.uint8)
    if (debug / "03_mask.png").is_file():
        predicted = np.array(Image.open(debug / "03_mask.png").convert("L"))
        if predicted.shape != auto_mask.shape:
            predicted = np.array(
                Image.fromarray(predicted).resize(original.size, Image.Resampling.NEAREST)
            )
        auto_mask = predicted
        Image.fromarray(auto_mask).save(destination / "mask.png")
    if (debug / "04_clean.jpg").is_file():
        Image.open(debug / "04_clean.jpg").convert("RGB").save(destination / "clean.png")
    _draw_markup(original, result.regions).save(destination / "markup.jpg", quality=90)
    _comparison(original, result.output_image).save(destination / "comparison.jpg", quality=90)
    payload = result.regions_payload()
    (destination / "regions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    overflow = [region.id for region in result.regions if region.overflow]
    metrics = None
    if annotation is not None:
        mask_path, zone_path = annotation
        perfect = load_perfect_mask_array(mask_path)
        if perfect.shape != (original.height, original.width):
            perfect = np.array(
                Image.fromarray(perfect).resize(original.size, Image.Resampling.NEAREST)
            )
        metrics = page_quality(
            np.array(original),
            auto_mask,
            perfect,
            destination / "clean.png",
            result.output_image,
            zone_path,
        )
        metrics.update(image=source.relative_to(root).as_posix(), regions=len(result.regions))
    note = {
        "stem": source.stem,
        "folder": folder,
        "file": source.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "has_mask": annotation is not None,
        "status": "pending",
        "engines": {"ocr": result.ocr_engine, "translator": result.translator_engine},
        "ocr_engine": result.ocr_engine,
        "translator_engine": result.translator_engine,
        "regions": len(result.regions),
        "overflow": overflow,
        "warnings": list(result.warnings),
        "min_font": _min_font(result.regions),
        "seconds": round(sum(result.timings.values()), 2),
        "eval": metrics,
        "leftover_letters": "",
        "missed_replicas": "",
        "split_phrases": "",
        "overflow_kegl": "",
        "fill_outline": "",
        "eaten_art": "",
        "notes": "",
    }
    return note


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=ROOT / "test-img")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--ocr", choices=("vlm", "rapid"), default="vlm")
    parser.add_argument("--translator", choices=("llm", "argos"), default="llm")
    parser.add_argument("--llm-url", default="http://192.168.88.37:8989/v1",
                        help="Тестовый LLM разработки; пустая строка оставляет config.json")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    out = args.out or ROOT / "output" / f"intake-{date.today().strftime('%Y%m%d')}"
    if (out / "eval.json").exists() or (out / "index.html").exists():
        parser.error(f"Каталог уже содержит отчёт: {out}")
    pages = list_intake_pages(args.images)
    if args.only:
        wanted = set(args.only)
        pages = [path for path in pages if path.stem in wanted or _folder_name(path, args.images) in wanted]
    if not pages:
        parser.error(f"Нет исходников в {args.images}")
    annotations = annotation_index(args.images)
    config = Config.load()
    config.ocr_backend = args.ocr
    config.translator_backend = args.translator
    config.sfx_mode = "replace"
    config.min_font_size = 10
    config.text_scale = 1.1
    if args.llm_url:
        config.llm_base_url = args.llm_url
    if args.llm_model:
        config.llm_model = args.llm_model
    pipeline = PagePipeline(config)
    out.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []
    eval_rows: list[dict] = []
    for source in pages:
        print(f"=== {source.relative_to(args.images).as_posix()} ===", flush=True)
        try:
            note = process_page(
                pipeline,
                source,
                args.images,
                out,
                annotations.get(source.resolve()),
            )
        except Exception as exc:
            note = {
                "stem": source.stem,
                "folder": _folder_name(source, args.images),
                "file": source.relative_to(args.images).as_posix(),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "has_mask": source.resolve() in annotations,
                "status": "pending",
                "error": str(exc),
                "eval": None,
                "notes": "прогон не завершился",
            }
            print(f"  ошибка: {exc}", flush=True)
        else:
            eval_row = note.get("eval")
            if eval_row:
                eval_rows.append(eval_row)
                print(
                    f"  {note['ocr_engine']}/{note['translator_engine']} "
                    f"recall={eval_row.get('ink_recall')} residue={eval_row.get('residue')} "
                    f"{note['seconds']}s",
                    flush=True,
                )
            else:
                print(
                    f"  {note['ocr_engine']}/{note['translator_engine']} без эталона {note['seconds']}s",
                    flush=True,
                )
        report.append(note)
        (out / "visual-notes.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    registry = [
        {
            "stem": page["stem"],
            "file": page.get("file"),
            "sha256": page.get("sha256"),
            "has_mask": page.get("has_mask"),
            "added": date.today().isoformat(),
            "status": "pending",
            "engines": page.get("engines") or {},
        }
        for page in report
    ]
    (out / "intake-registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "eval.json").write_text(json.dumps(eval_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_html(out, report)
    print(f"Готово: {out / 'index.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
