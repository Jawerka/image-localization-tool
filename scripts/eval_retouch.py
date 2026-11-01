#!/usr/bin/env python3
"""Сравнение очистки на фиксированных детекциях; эталоны доступны только оценщику."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_pipeline import find_pairs, page_quality
from src.components.bubble_detector import BubbleDetector
from src.components.text_regions import build_regions
from src.config import Config
from src.models import TextRegion
from src.page_pipeline import PagePipeline, _composite_changes, _layout_scale
from src.utils.mask_metrics import load_perfect_mask_array


def reference_similarity(original, automatic, reference, zone):
    """Доля улучшения относительно контрольной очистки, не процент качества рисунка."""
    selected = zone > 0
    if not np.any(selected):
        return None
    source = np.asarray(original).astype(np.float32)[selected]
    target = np.asarray(reference).astype(np.float32)[selected]
    result = np.asarray(automatic).astype(np.float32)[selected]
    change = float(np.abs(source - target).mean())
    if change < 1.0:
        return None
    return round(1.0 - float(np.abs(result - target).mean()) / change, 5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=ROOT / 'test-img')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--only', nargs='+')
    args = parser.parse_args()
    if (args.out / 'eval.json').exists():
        parser.error('Каталог уже содержит отчёт; выберите новый --out, чтобы сохранить сравнение')
    pairs = find_pairs(args.images)
    if args.only:
        pairs = [p for p in pairs if p[0].stem in args.only]
    if not pairs:
        parser.error('Нет подходящих эталонных пар')
    config = Config()
    detector = BubbleDetector(intra_op_threads=4)
    pipeline = PagePipeline(config)
    report = []
    args.out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'src/page_pipeline.py', *sorted((ROOT / 'src/components').glob('*.py'))]
    manifest = {
        'python': platform.python_version(),
        'config': {key: getattr(config, key) for key in ('layout_long_side', 'adaptive_text', 'letter_mask_grow_px', 'bubble_mask_inset_px', 'inpainter_backend')},
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'scope': 'Фиксированные детекции ogkalu, технические непустые тексты; OCR и перевод исключены',
    }
    (args.out / 'run.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for source, annotation, zone_path in pairs:
        relative = source.relative_to(args.images)
        destination = args.out / relative.with_suffix('')
        destination.mkdir(parents=True, exist_ok=True)
        image = Image.open(source).convert('RGB')
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        cached = args.baseline / relative.with_suffix('') if args.baseline else None
        if cached:
            metadata = json.loads((cached / 'input.json').read_text(encoding='utf-8'))
            if metadata['sha256'] != source_hash:
                raise ValueError(f'Изменился исходник: {source}')
            payload = json.loads((cached / 'regions.json').read_text(encoding='utf-8'))
        else:
            regions = build_regions(detector.detect(image))
            for region in regions:
                region.text = 'TEST TEXT'
                region.translation = 'ТЕСТ'
            payload = [r.to_dict() for r in regions]
        (destination / 'regions.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        (destination / 'input.json').write_text(json.dumps({'sha256': source_hash, 'size': image.size}), encoding='utf-8')
        regions = [TextRegion.from_dict(r) for r in payload]
        warnings = []
        started = time.perf_counter()
        predicted, cleaned = pipeline.clean(image, regions, warnings=warnings)
        cleaned.save(destination / 'clean.png')
        Image.fromarray(predicted).save(destination / 'mask.png')
        # Эталон открывается только после завершения автоматической очистки.
        perfect = load_perfect_mask_array(annotation)
        if perfect.shape != (image.height, image.width):
            perfect = np.array(Image.fromarray(perfect).resize(image.size, Image.Resampling.NEAREST))
        metrics = page_quality(np.array(image), predicted, perfect, destination / 'clean.png', cleaned, zone_path)
        metrics.update(image=relative.as_posix(), seconds=round(time.perf_counter()-started, 2), warnings=warnings, regions=len(regions))
        if args.reference:
            work, _ = _layout_scale(image, config.layout_long_side)
            ref_mask = np.array(Image.fromarray(perfect).resize(work.size, Image.Resampling.NEAREST))
            # Контроль: полная разметка текста и восстановление рисунка без плоских заливок.
            reference = pipeline._inpaint(work, ref_mask, warnings, allow_flat_fill=False)
            reference = _composite_changes(image, work, reference)
            reference.save(destination / 'reference.png')
            metrics['reference_similarity'] = reference_similarity(image, cleaned, reference, perfect)
        if cached:
            old_rows = json.loads((args.baseline / 'eval.json').read_text(encoding='utf-8'))
            old = next(r for r in old_rows if r['image'] == relative.as_posix())
            metrics['delta'] = {k: round(metrics[k] - old[k], 6) for k in ('ink_recall', 'residue', 'halo', 'damage') if metrics[k] is not None and old[k] is not None}
            metrics['coverage_regression'] = metrics['delta'].get('ink_recall', 0) < -0.005
        report.append(metrics)
        (args.out / 'eval.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(metrics, ensure_ascii=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
