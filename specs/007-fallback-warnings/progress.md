# Progress: 007 Fallback Warnings

**Started**: 2026-10-09
**Status**: Done

## Done

- `LamaInpainter.last_warnings` on unexpected OpenCV fallback.
- `page_pipeline._inpaint` merges those into page warnings.
- `_mentions_fallback` remains OCR/Argos-only (FR-003).
- `applyDetail` shows `pipeline` banner from document.warnings.
- Unit: `test_lama_failure_records_opencv_fallback_warning`, `test_fallback_warnings.py`.

## Converge

B8 addressed for OCR/Argos/LaMa visibility. Full vs-etalon QA report still ROADMAP.
