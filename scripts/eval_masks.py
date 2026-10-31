#!/usr/bin/env python3
"""Оценка маски по виду эталона: покрытие букв и попадание внутрь разметки.

Эталон только для отчёта. sound-ref считает звуки, 002_eng — всё,
остальные страницы — текст без звуков. Переопределение: ``--scope имя=sfx|text|all``.

Полный проход сохраняет регионы. ``--reuse-regions`` пересчитывает только маску.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_pipeline import find_pairs
from src.config import Config
from src.models import TextRegion
from src.page_pipeline import PagePipeline
from src.utils.mask_metrics import extract_ink, ink_report, load_perfect_mask_array

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_SCOPES = ("sfx", "text", "all")
# Запас в пикселях исходника. Второй запас — те же 6 px на рабочем длинном крае 2000.
_MARGIN_PX = 6
_WORK_LONG = 2000


def _folder_name(path: Path, root: Path) -> str:
    """Стабильное имя каталога: повторный прогон попадает в ту же папку."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = Path(path.name)
    stem = relative.with_suffix("").as_posix()
    return stem.replace("/", "__").replace(" ", "_").replace("(", "").replace(")", "")


def scope_of(path: Path, overrides: list[tuple[str, str]]) -> str:
    """Вид эталона: явный флаг, затем каталог звуков и смешанная страница."""
    folded = str(path).casefold()
    for name, scope in overrides:
        if name.casefold() in folded:
            return scope
    if "sound-ref" in path.parts:
        return "sfx"
    if path.stem == "002_eng":
        return "all"
    return "text"


def list_pages(root: Path) -> list[Path]:
    """Страницы без файлов разметки и без сохранённого html."""
    pages = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if "html" in path.parts:
            continue
        stem = path.stem.casefold()
        if stem.endswith("-mask") or stem.endswith("_mask") or stem.endswith("-mask-2"):
            continue
        pages.append(path)
    return pages


def _pairs(root: Path) -> dict[str, Path]:
    return {str(image.resolve()): mask for image, mask, _zone in find_pairs(root)}


def _margin_scaled(shape: tuple[int, int]) -> int:
    """6 px на длинной стороне 2000, пересчитанные в пиксели исходника."""
    long_side = max(shape)
    if long_side <= _WORK_LONG:
        return _MARGIN_PX
    return int(round(_MARGIN_PX * long_side / _WORK_LONG))


def _wanted(block_type: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "sfx":
        return block_type == "sfx"
    return block_type != "sfx"


def scoped_components(
    mask: np.ndarray,
    regions: list[TextRegion],
    scope: str,
) -> tuple[np.ndarray, dict[int, tuple[str, str]]]:
    """Компоненты маски, пересекающие регион нужного вида.

    Второй результат — id компоненты → (тип региона, короткий текст).
    Компонент без пересечения в выборку не входит.
    """
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    selected = np.zeros(mask.shape, dtype=bool)
    owners: dict[int, tuple[str, str]] = {}
    if count <= 1:
        return selected, owners
    boxes = []
    for region in regions:
        x, y, w, h = region.bbox
        boxes.append((region, x - 12, y - 12, x + w + 12, y + h + 12))
    for index in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[index])
        component = labels[y:y + h, x:x + w] == index
        best = None
        best_overlap = 0
        for region, x0, y0, x1, y1 in boxes:
            ix0, iy0 = max(x, x0), max(y, y0)
            ix1, iy1 = min(x + w, x1), min(y + h, y1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            overlap = int(np.count_nonzero(component[iy0 - y:iy1 - y, ix0 - x:ix1 - x]))
            if overlap > best_overlap:
                best_overlap = overlap
                best = region
        if best is None or not _wanted(best.block_type, scope):
            continue
        selected[y:y + h, x:x + w][component] = True
        owners[index] = (best.block_type, (best.text or "")[:24])
    return selected, owners


def _hit(scoped: np.ndarray, gt: np.ndarray, margin: int) -> float | None:
    total = int(np.count_nonzero(scoped))
    if total == 0:
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin * 2 + 1, margin * 2 + 1))
    allowed = cv2.dilate((gt > 0).astype(np.uint8), kernel) > 0
    return float(np.count_nonzero(scoped & allowed) / total)


def _blobs(binary: np.ndarray, limit: int, minimum: int) -> list[dict]:
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(binary.astype(np.uint8))
    rows = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < minimum:
            continue
        rows.append({"x": x, "y": y, "w": w, "h": h, "pixels": area})
    rows.sort(key=lambda item: item["pixels"], reverse=True)
    return rows[:limit]


def _false_regions(mask: np.ndarray, gt: np.ndarray, regions: list[TextRegion]) -> int:
    """Регионы, у которых больше половины маски лежит вне эталона."""
    false = 0
    height, width = mask.shape[:2]
    for region in regions:
        x, y, box_w, box_h = (int(v) for v in region.bbox)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + box_w), min(height, y + box_h)
        if x1 <= x0 or y1 <= y0:
            continue
        local = mask[y0:y1, x0:x1] > 0
        pixels = int(np.count_nonzero(local))
        if pixels < 12:
            continue
        inside = int(np.count_nonzero(local & (gt[y0:y1, x0:x1] > 0)))
        if inside * 2 < pixels:
            false += 1
    return false


def _missed_components(mask: np.ndarray, gt: np.ndarray) -> int:
    """Компоненты эталона, которые маска почти не закрыла."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats((gt > 0).astype(np.uint8))
    missed = 0
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 30:
            continue
        component = labels == index
        covered = int(np.count_nonzero(component & (mask > 0)))
        if covered < area * 0.2:
            missed += 1
    return missed


def _proposal_recall(seg: np.ndarray | None, ink: np.ndarray) -> float | None:
    """Доля чернил эталона, которую закрывает карта второго детектора."""
    if seg is None or not np.any(ink):
        return None
    if seg.shape[:2] != ink.shape[:2]:
        seg = cv2.resize(seg, (ink.shape[1], ink.shape[0]), interpolation=cv2.INTER_NEAREST)
    return round(float(np.count_nonzero((seg > 0) & ink) / np.count_nonzero(ink)), 4)


def measure(
    image: np.ndarray,
    mask: np.ndarray,
    gt: np.ndarray,
    regions: list[TextRegion],
    scope: str,
) -> dict:
    """Покрытие всех чернил и попадание маски нужного вида."""
    extraction = extract_ink(image, gt)
    report = ink_report((mask > 0).astype(np.uint8) * 255, extraction)
    scoped, _owners = scoped_components(mask, regions, scope)
    scaled = _margin_scaled(mask.shape[:2])
    ink = extraction.mask > 0
    missed = ink & ~(mask > 0)
    allowed = cv2.dilate((gt > 0).astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (_MARGIN_PX * 2 + 1, _MARGIN_PX * 2 + 1)
    )) > 0
    extra = scoped & ~allowed
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    misses = _blobs(missed, 8, 30)
    for blob in misses:
        patch = missed[blob["y"]:blob["y"] + blob["h"], blob["x"]:blob["x"] + blob["w"]]
        values = gray[blob["y"]:blob["y"] + blob["h"], blob["x"]:blob["x"] + blob["w"]][patch]
        blob["gray"] = int(np.median(values)) if values.size else None
    return {
        "scope": scope,
        "recall": report["recall"],
        "status": report["status"],
        "ink_pixels": report["ink_pixels"],
        "hit6": _hit(scoped, gt, _MARGIN_PX),
        "hit_scaled": _hit(scoped, gt, scaled),
        "scaled_margin_px": scaled,
        "scoped_pixels": int(np.count_nonzero(scoped)),
        "missed_ink": int(np.count_nonzero(missed)),
        "extra_pixels": int(np.count_nonzero(extra)),
        "other_kind_pixels": int(np.count_nonzero((mask > 0) & ~scoped)),
        "misses": misses,
        "extras": _blobs(extra, 8, 80),
        "false_regions": _false_regions(mask, gt, regions),
        "missed_components": _missed_components(mask, gt),
    }


def _diff_image(image: np.ndarray, mask: np.ndarray, gt: np.ndarray, scoped: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Зелёный — попадание, красный — мимо эталона, жёлтый — пропуск, синий — другой вид."""
    canvas = (image.astype(np.float32) * 0.45).astype(np.uint8)
    allowed = cv2.dilate((gt > 0).astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (_MARGIN_PX * 2 + 1, _MARGIN_PX * 2 + 1)
    )) > 0
    canvas[scoped & allowed] = (40, 170, 60)
    canvas[scoped & ~allowed] = (220, 40, 40)
    canvas[ink & ~(mask > 0)] = (230, 200, 40)
    canvas[(mask > 0) & ~scoped] = (50, 90, 220)
    return canvas


def _gt_view(image: np.ndarray, gt: np.ndarray) -> np.ndarray:
    canvas = (image.astype(np.float32) * 0.55).astype(np.uint8)
    canvas[gt > 0] = (220, 30, 30)
    return canvas


def _mask_view(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    canvas = image.copy()
    canvas[mask > 0] = (canvas[mask > 0].astype(np.float32) * 0.55 + np.array([255, 30, 30]) * 0.45).astype(np.uint8)
    return canvas


def _save(path: Path, array: np.ndarray) -> None:
    Image.fromarray(array).save(path, quality=85)


def _load_regions(path: Path) -> tuple[list[TextRegion], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    regions = [TextRegion.from_dict(item) for item in payload["regions"]]
    # Повторная подготовка должна увидеть текущий алгоритм, а не старый отступ.
    for region in regions:
        region.auto_layout = None
    return regions, payload


def _pipeline(args: argparse.Namespace | None = None) -> PagePipeline:
    detector = getattr(args, "detector", "ogkalu") or "ogkalu"
    ocr = getattr(args, "ocr", "rapid") or "rapid"
    mode = "ogkalu" if detector == "ogkalu-low" else detector
    options = dict(
        ocr_backend="vlm" if ocr == "vlm" else "rapid",
        translator_backend="llm" if ocr == "vlm" else "argos",
        sfx_mode="replace",
        discover_missing_text=bool(getattr(args, "discover", False)),
        ort_intra_op_threads=4,
        detector_mode=mode,
        detector_conf=0.15 if detector == "ogkalu-low" else 0.3,
        ctd_conf=float(getattr(args, "ctd_conf", 0.4) or 0.4),
        ctd_seg_clip=bool(getattr(args, "seg_clip", False)),
    )
    llm_url = str(getattr(args, "llm_url", "") or "").strip()
    llm_model = str(getattr(args, "llm_model", "") or "").strip()
    if llm_url:
        options["llm_base_url"] = llm_url
    if llm_model:
        options["llm_model"] = llm_model
    pipe = PagePipeline(Config(**options))
    pipe._inpaint = lambda image, *args, **kwargs: image
    return pipe


def _gallery(out: Path, rows: list[dict]) -> None:
    cards = []
    for row in rows:
        folder = row["folder"]
        metrics = row.get("metrics") or {}
        recall = metrics.get("recall")
        hit6 = metrics.get("hit6")
        hit_scaled = metrics.get("hit_scaled")
        text = (
            f"{row['name']} · {metrics.get('scope', 'нет эталона')}"
            f"<br>покрытие {recall if recall is not None else '—'} · "
            f"попадание 6px {hit6 if hit6 is not None else '—'} · "
            f"попадание к 2000px {hit_scaled if hit_scaled is not None else '—'}"
        )
        shots = []
        for name in ("original.jpg", "reference.jpg", "mask.jpg", "diff.jpg"):
            file = out / folder / name
            if file.is_file():
                shots.append(f"<img src='{folder}/{name}'>")
        cards.append(f"<figure><figcaption>{text}</figcaption>{''.join(shots)}</figure>")
    html = """<!doctype html><meta charset="utf-8"><title>Маски</title>
<style>
body { font: 14px sans-serif; background: #111; color: #eee; }
figure { margin: 12px; }
img { max-width: 24%; vertical-align: top; }
</style>
<p>Слева направо: оригинал, эталон, маска алгоритма, карта.
Зелёный — попадание в эталон своего вида, красный — маска мимо эталона,
жёлтый — не закрытые чернила, синий — маска другого вида.</p>
""" + "\n".join(cards)
    (out / "gallery.html").write_text(html, encoding="utf-8")


def _compare(rows: list[dict], previous: Path) -> None:
    old = {item["name"]: item for item in json.loads(previous.read_text(encoding="utf-8"))}
    print("сравнение с", previous)
    for row in rows:
        before = (old.get(row["name"]) or {}).get("metrics") or {}
        after = row.get("metrics") or {}
        if not before or not after:
            continue
        for key in ("recall", "hit6", "hit_scaled"):
            a, b = before.get(key), after.get(key)
            if a is None or b is None:
                continue
            delta = (b - a) * 100
            if abs(delta) >= 0.5:
                print(f"  {row['name']} {key} {a:.4f} -> {b:.4f} ({delta:+.2f} п.п.)")


def run(args: argparse.Namespace) -> None:
    root = Path(args.images)
    out = Path(args.out) / args.run
    out.mkdir(parents=True, exist_ok=True)
    masks = _pairs(root)
    overrides = []
    for item in args.scope or []:
        name, _, scope = item.partition("=")
        if scope not in _SCOPES or not name:
            raise SystemExit(f"--scope ждёт имя=sfx|text|all, получено {item}")
        overrides.append((name, scope))
    pages = list_pages(root)
    if args.only:
        wanted = {item.casefold() for item in args.only}
        pages = [path for path in pages if path.stem.casefold() in wanted or any(item in str(path).casefold() for item in wanted)]
    pipe = None if args.reuse_regions else _pipeline(args)
    report = []
    for path in pages:
        folder = out / _folder_name(path, root)
        folder.mkdir(parents=True, exist_ok=True)
        image = Image.open(path).convert("RGB")
        rgb = np.array(image)
        if args.reuse_regions:
            source_dir = Path(args.regions_from) / _folder_name(path, root) if args.regions_from else folder
            source = source_dir / "regions.json"
            regions, _payload = _load_regions(source)
            if pipe is None:
                pipe = _pipeline(args)
            mask, _cleaned = pipe.clean(image, regions)
        else:
            result = pipe.analyze(image, str(path), "en", "ru")
            regions = result.regions
            (folder / "regions.json").write_text(
                json.dumps(result.regions_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # analyze уже записал auto_layout. Маска считается заново тем же кодом.
            for region in regions:
                region.auto_layout = None
            mask, _cleaned = pipe.clean(image, regions)
        Image.fromarray(mask).save(folder / "mask.png")
        _save(folder / "original.jpg", rgb)
        _save(folder / "mask.jpg", _mask_view(rgb, mask > 0))
        gt_path = masks.get(str(path.resolve()))
        row = {"folder": folder.name, "name": path.name, "path": str(path), "regions": len(regions)}
        if not args.reuse_regions:
            row["timings"] = dict(getattr(result, "timings", {}) or {})
            row["warnings"] = list(getattr(result, "warnings", []) or [])
        if gt_path is not None:
            gt = load_perfect_mask_array(gt_path)
            if gt.shape[:2] != mask.shape[:2]:
                gt = np.array(Image.fromarray(gt).resize(image.size, Image.Resampling.NEAREST))
            scope = scope_of(path, overrides)
            metrics = measure(rgb, mask, gt, regions, scope)
            ink = extract_ink(rgb, gt).mask > 0
            seg = getattr(pipe, "ctd_seg", None)
            proposal = _proposal_recall(seg, ink)
            if proposal is not None:
                metrics["proposal_recall"] = proposal
            row["metrics"] = metrics
            scoped, _owners = scoped_components(mask, regions, scope)
            _save(folder / "reference.jpg", _gt_view(rgb, gt))
            _save(folder / "diff.jpg", _diff_image(rgb, mask, gt, scoped, ink))
        else:
            _save(folder / "diff.jpg", _mask_view(rgb, mask > 0))
        report.append(row)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        shown = row.get("metrics") or {}
        print(
            f"{row['folder']} {path.name} recall={shown.get('recall')} "
            f"hit6={shown.get('hit6')} hit_scaled={shown.get('hit_scaled')}",
            flush=True,
        )
    _gallery(out, report)
    if args.compare:
        _compare(report, Path(args.compare))
    print("DONE", out, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценка масок по виду эталона")
    parser.add_argument("--images", default="test-img")
    parser.add_argument("--out", default="output/mask-eval")
    parser.add_argument("--run", default="baseline")
    parser.add_argument("--reuse-regions", action="store_true")
    parser.add_argument("--regions-from", default="", help="Каталог прогона, откуда взять regions.json")
    parser.add_argument("--scope", action="append", default=[], help="имя=sfx|text|all")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--compare", default="")
    parser.add_argument("--ocr", choices=("rapid", "vlm"), default="rapid")
    parser.add_argument("--detector", choices=("ogkalu", "ctd", "both", "ogkalu-low"), default="ogkalu")
    parser.add_argument("--seg-clip", action="store_true", help="Обрезать маску обведённого звука картой CTD")
    parser.add_argument("--llm-url", default="", help="Адрес языковой модели, пусто — из Config")
    parser.add_argument("--llm-model", default="", help="Имя модели, пусто — первая с /v1/models")
    parser.add_argument("--discover", action="store_true", help="Искать пропущенные надписи языковой моделью")
    parser.add_argument("--ctd-conf", type=float, default=0.4, help="Порог второго детектора")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
