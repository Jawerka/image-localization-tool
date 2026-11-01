"""Очистка с настоящими сохранёнными OCR-регионами; эталоны только для оценки."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.eval_masks import _folder_name, measure, scope_of
from scripts.eval_pipeline import find_pairs
from src.config import Config
from src.models import TextRegion, TextStyle
from src.page_pipeline import PagePipeline
from src.utils.mask_metrics import load_perfect_mask_array
from src.utils.paths import resolve_model


def restore_regions(payload):
    """Сбросить вычисленную геометрию, сохранив пользовательские правки."""
    regions = [TextRegion.from_dict(row) for row in payload['regions']]
    for region in regions:
        if not region.manual and not region.edited and not region.layout_snapshot:
            region.auto_layout = None
            region.style = TextStyle()
    return regions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regions', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--only', default='')
    args = parser.parse_args()
    if (args.out / 'report.json').exists():
        parser.error('Отчёт уже существует: выберите новый каталог')
    args.out.mkdir(parents=True, exist_ok=True)
    config = Config()
    pipeline = PagePipeline(config)
    manifest = {'scope': 'Сохранённые настоящие OCR-регионы; перевод может быть исходным текстом при отсутствии Argos',
                'regions': str(args.regions.resolve()),
                'config': {key: getattr(config, key) for key in ('layout_long_side', 'sfx_mode', 'adaptive_text', 'inpainter_backend')},
                'models': {name: str(resolve_model(name).resolve()) for name in ('ogkalu-detector-v4-s_int8.onnx', 'anime-manga-big-lama.pt')},
                'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (ROOT / 'src/components').glob('*.py')}}
    (args.out / 'run.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    old = json.loads((args.baseline / 'report.json').read_text(encoding='utf-8')) if args.baseline else []
    rows = []
    for source, annotation, _zone in find_pairs(ROOT / 'test-img'):
        if args.only and args.only not in str(source):
            continue
        name = _folder_name(source, ROOT / 'test-img')
        payload = json.loads((args.regions / name / 'regions.json').read_text(encoding='utf-8'))
        regions = restore_regions(payload)
        warnings = list(payload.get('warnings', []))
        image = Image.open(source).convert('RGB')
        mask, clean = pipeline.clean(image, regions, warnings=warnings)
        dest = args.out / name
        dest.mkdir(exist_ok=True)
        clean.save(dest / 'clean.png')
        Image.fromarray(mask).save(dest / 'mask.png')
        # Разметка не передаётся ни детектору, ни очистке.
        gt = load_perfect_mask_array(annotation)
        if gt.shape != mask.shape:
            gt = np.array(Image.fromarray(gt).resize(image.size, Image.Resampling.NEAREST))
        row = measure(np.array(image), mask, gt, regions, scope_of(source, []))
        row.update(image=source.relative_to(ROOT / 'test-img').as_posix(), warnings=warnings,
                   stages={'detected_regions': len(regions),
                           'read_regions': sum(bool(r.text.strip()) for r in regions),
                           'sfx_regions': sum(r.block_type == 'sfx' for r in regions),
                           'skipped_regions': sum(r.skip for r in regions)},
                   source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   regions_sha256=hashlib.sha256((args.regions / name / 'regions.json').read_bytes()).hexdigest())
        previous = next((r for r in old if r['image'] == row['image']), None)
        if previous:
            row['delta'] = {k: row[k] - previous[k] for k in ('recall', 'hit6', 'extra_pixels')}
            row['coverage_regression'] = row['delta']['recall'] < -0.005
        rows.append(row)
        (args.out / 'report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: row[k] for k in ('image', 'recall', 'hit6')}, ensure_ascii=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
