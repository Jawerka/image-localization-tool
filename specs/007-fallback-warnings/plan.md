# Implementation Plan: Fallback Warnings

**Branch**: `007-fallback-warnings` | **Date**: 2026-10-09

## Design

| Area | Change |
|------|--------|
| `lama_inpainter.py` | `last_warnings` on unexpected OpenCV fallback |
| `page_pipeline._inpaint` | merge `inpainter.last_warnings` into page warnings |
| `worker._mentions_fallback` | keep OCR/Argos only (FR-003) |
| `state.js` `applyDetail` | banner for document.warnings |

## Tests

- Extend `test_lama_inpainter.py` for fallback warning.
- Unit for `_mentions_fallback` OpenCV-only → False.
- Optional light test that normalize/apply path sets banner — prefer calling a small exported helper if needed.
