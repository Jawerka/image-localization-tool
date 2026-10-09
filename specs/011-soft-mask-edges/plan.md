# Plan: 011 Soft Mask Edges

- `_EDGE_FEATHER_PX = 4` in `lama_inpainter.py`
- `_edge_alpha(hole, feather)` via `cv2.distanceTransform`
- Soft blend in `_paste_component` (covers LaMa single-pass, tiles→paste, OpenCV)
- `_lama_tiles` final hole write multiplies by the same edge alpha when combining into crop (shared helper), so tile output already respects edge fade before page paste uses hard component copy of already-soft pixels — **avoid double feather**: tiles keep hard predicted accumulation; only `_paste_component` soft-blends against the page.
