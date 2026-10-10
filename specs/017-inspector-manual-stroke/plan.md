# Plan: Stable Inspector, Manual Translation, Stroke Width

- `web/js/inspector_render.js` — content key + skip gate
- `web/js/inspector.js` — gate rebuild, all-details capture, stroke_width, lock on translation
- `src/models.py` — `translation_locked`
- `src/components/llm_translator.py` — skip locked in `_apply_items` / Argos paths
- tests for key/skip, lock, stroke_width
