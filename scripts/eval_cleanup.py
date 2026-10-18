"""Проверить остаточный текст на очищенной странице до вёрстки перевода.

Пример: python scripts/eval_cleanup.py output/case --output output/case/quality
Подозрительные области требуют визуальной проверки: OCR может читать рисунок.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.components.rapid_ocr import RapidOcr
from src.models import TextRegion, should_translate


def residual_candidates(words, regions):
    """Сопоставить OCR очищенной страницы с областями переведённого текста."""
    findings = []
    for word in words:
        if word.confidence < 0.6 or sum(c.isalnum() for c in word.text) < 2:
            continue
        x, y, w, h = word.bbox
        if w <= 0 or h <= 0:
            continue
        matches = []
        for region in regions:
            bx, by, bw, bh = region.bbox
            overlap = max(0, min(x+w, bx+bw)-max(x, bx)) * max(0, min(y+h, by+bh)-max(y, by))
            if overlap / (w*h) >= 0.5:
                matches.append(region.id)
        if matches:
            findings.append(dict(region_ids=matches, text=word.text, bbox=list(word.bbox), confidence=float(word.confidence)))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path, help='Каталог с regions.json и 04_clean.jpg/png')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-sfx', action='store_true')
    args = parser.parse_args()
    data = json.loads((args.case / 'regions.json').read_text('utf-8'))
    regions = [TextRegion.from_dict(r) for r in data['regions']]
    drawable = [r for r in regions if r.translation.strip() and should_translate(r, args.include_sfx)]
    clean_path = args.case / '04_clean.png'
    if not clean_path.exists():
        clean_path = args.case / '04_clean.jpg'
    clean = Image.open(clean_path).convert('RGB')
    findings = residual_candidates(RapidOcr(min_confidence=0.6)._words(clean), drawable)
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(
        cleaned_path=str(clean_path.resolve()),
        checked_region_ids=[r.id for r in drawable],
        candidate_region_ids=sorted({i for f in findings for i in f['region_ids']}),
        candidates=findings,
        limitation='Кандидаты OCR, не доказательство дефекта. Пустой список не гарантирует очистку. Пропущенные детектором блоки не проверены.',
    )
    (args.output / 'cleanup.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    draw = ImageDraw.Draw(clean)
    for finding in findings:
        x, y, w, h = finding['bbox']
        draw.rectangle((x, y, x+w, y+h), outline='red', width=3)
        draw.text((x, max(0, y-12)), ','.join(map(str, finding['region_ids'])), fill='red')
    clean.save(args.output / 'candidates.png')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
