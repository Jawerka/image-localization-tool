"""Сравнить основной пайплайн с сохранёнными опытами без повторного OCR."""
from __future__ import annotations

import argparse
import json
import html
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import Config
from src.models import TextRegion
from src.page_pipeline import PagePipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'output/sfx-experiments/old-tests')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/sfx-experiments/integrated-candidate')
    parser.add_argument('--case', default='')
    parser.add_argument('--layout-only', action='store_true')
    parser.add_argument('--reuse-clean', action='store_true')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    config = Config(layout_long_side=0, sfx_mode='replace', translate_sfx=True, models_dir=str(ROOT / 'models'))
    config.ort_intra_op_threads = 4
    pipeline = PagePipeline(config)
    records = json.loads((args.output / 'report.json').read_text('utf-8')) if args.case and (args.output / 'report.json').is_file() else []
    for folder in sorted(args.cache.iterdir()):
        if not (folder / 'regions.json').is_file() or (args.case and args.case not in folder.name):
            continue
        payload = json.loads((folder / 'regions.json').read_text('utf-8'))
        source = Path(payload['source_path'])
        image = Image.open(source).convert('RGB')
        regions = [TextRegion.from_dict(raw) for raw in payload['regions']]
        # Кэш опытов содержит изменённые кегли/цвета. Сохраняем исходные OCR/переводы,
        # а автоматические параметры вычисляем так же, как при новой обработке.
        for region in regions:
            region.layout_snapshot = None
            region.auto_layout = None
            if not region.edited and not region.manual:
                from src.models import TextStyle
                region.style = TextStyle()
        run = json.loads((folder / 'run.json').read_text('utf-8'))
        target = run.get('target', 'ru')
        pipeline.typesetter.lang = target
        out = args.output / folder.name
        out.mkdir(exist_ok=True)
        warnings = []
        start = time.perf_counter()
        print('START', source.name, flush=True)
        if args.layout_only or (args.reuse_clean and (out / 'clean.png').is_file()):
            from src.components.adaptive_text import prepare_regions
            from src.components.text_segmenter import segment_regions
            prepare_regions(image, pipeline._drawable(regions))
            segment_regions(image, [r for r in pipeline._drawable(regions) if not r.auto_layout or
                                    (r.auto_layout.get('kind') == 'bubble' and r.bubble_bbox is not None)])
            clean = Image.open(out / 'clean.png' if args.reuse_clean else folder / 'clean.png').convert('RGB')
        else:
            mask, clean = pipeline.clean(image, regions, warnings=warnings)
            Image.fromarray(mask).save(out / 'mask.png')
            clean.save(out / 'clean.png')
        result, overflow = pipeline.typeset_image(clean, pipeline._drawable(regions), target, warnings)
        result.save(out / 'result.png')
        (out / 'regions.json').write_text(json.dumps([r.to_dict() for r in regions], ensure_ascii=False, indent=2), 'utf-8')
        reference = Image.open(folder / 'rotated.png').convert('RGB')
        thumbs = [ImageOps.contain(im, (650, 950)) for im in (image, reference, result)]
        sheet = Image.new('RGB', (1950, max(t.height for t in thumbs) + 55), '#e8edf3')
        draw = ImageDraw.Draw(sheet)
        for index, (label, thumb) in enumerate(zip(('A / original', 'B / approved experiment', 'C / integrated pipeline'), thumbs)):
            draw.text((index * 650 + 15, 15), label, fill='black')
            sheet.paste(thumb, (index * 650 + (650 - thumb.width) // 2, 50))
        sheet.save(out / 'comparison.jpg', quality=94)
        record = dict(file=source.name, regions=len(regions), overflow=overflow, warnings=warnings,
                      drawable=len(pipeline._drawable(regions)),
                      mode='cached-clean' if args.layout_only or args.reuse_clean else 'full-clean-and-render',
                      seconds=round(time.perf_counter() - start, 2),
                      changed_pixels=int(np.count_nonzero(np.any(np.asarray(result) != np.asarray(reference), axis=2))),
                      rotated=[r.id for r in regions if r.auto_layout and r.style.rotation],
                      result=str(out / 'result.png'))
        records = [row for row in records if row['file'] != record['file']]
        records.append(record)
        print('DONE', json.dumps(record, ensure_ascii=True), flush=True)
    (args.output / 'report.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), 'utf-8')
    records.sort(key=lambda row: row['file'])
    (args.output / 'report.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), 'utf-8')
    cards = ''.join(f'<article><h2>{html.escape(r["file"])}</h2><img loading="lazy" src="{html.escape(Path(r["result"]).parent.name)}/comparison.jpg"><p>Overflow: {r["overflow"]}; warnings: {html.escape(str(r["warnings"]))}</p></article>' for r in records)
    (args.output / 'index.html').write_text('<meta charset="utf-8"><title>Adaptive text verification</title><style>body{font:16px sans-serif;background:#eef2f7}img{max-width:100%}article{margin:25px}</style>' + cards, 'utf-8')


if __name__ == '__main__':
    main()
