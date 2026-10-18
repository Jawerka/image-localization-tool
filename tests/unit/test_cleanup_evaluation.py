"""Проверка ретуши сообщает кандидатов, не принимает соседний текст за остаток."""

from scripts.eval_cleanup import residual_candidates
from src.components.rapid_ocr import OcrWord
from src.models import TextRegion


def test_cleanup_candidates_require_confidence_text_and_region_overlap():
    regions = [TextRegion(7, (10, 10, 100, 40))]
    words = [
        OcrWord('HELLO', (20, 20, 50, 15), 0.95),
        OcrWord('outside', (120, 20, 50, 15), 0.99),
        OcrWord('noise', (20, 20, 50, 15), 0.4),
        OcrWord('...', (20, 20, 50, 15), 0.99),
        OcrWord('edge', (105, 20, 50, 15), 0.99),
    ]
    found = residual_candidates(words, regions)
    assert len(found) == 1
    assert found[0]['region_ids'] == [7]
    assert found[0]['text'] == 'HELLO'


def test_cleanup_empty_scope_cannot_report_skipped_regions():
    assert residual_candidates([OcrWord('JIGGLE', (0, 0, 40, 10), 0.99)], []) == []
