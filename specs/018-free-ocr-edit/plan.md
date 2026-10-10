# Plan: Free-Text Crop OCR + Editable Original

- `src/components/vlm_ocr.py` — free regions: loop `read_crop` only; balloons unchanged
- `tests/unit/test_vlm_ocr.py` — free pass has no page prompts; balloon scramble warning remains
- `web/js/inspector.js` — editable original `data-field="text"`, `onField` + `SLOW`
- `tests/js/` — assert text field wiring if a small unit helper is practical; otherwise cover via inspector_render key including text
