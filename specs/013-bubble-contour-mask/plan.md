# Implementation Plan: Bubble Contour Mask

**Branch**: `013-bubble-contour-mask`  
**Date**: 2026-10-10  
**Spec**: [spec.md](./spec.md)

## Summary

Replace AABB-clipped flood + inscribed-ellipse retouch with edge-aware balloon interior silhouette so dialogue cleanup neither paints detector-box corners outside the bubble nor leaves a thick uncleared ring inside the outline.

## Constitution check

- Pipeline v2 entry unchanged.
- New algorithm in new file `src/components/bubble_contour.py`.
- Config defaults for inset / barrier.
- Russian docstrings.
- No models committed.

## Technical approach

1. `bubble_interior_mask(rgb, region, *, inset_px, …) -> uint8 mask`
   - ROI = bubble_bbox + small pad (search only).
   - Seed = light pixel near text bbox center.
   - Barrier = dark relative to seed OR Canny edges on ROI.
   - Flood / CC on light non-barrier pixels from seed; fill letter holes.
   - Erode by `inset_px` (default 2).
2. `bubble_retouch_mask` in text_segmenter calls this; on empty → ink dilated in text crop only (existing path), **not** `_inscribed_ellipse`.
3. `Config.bubble_mask_inset_px: int = 2`.
4. Unit fixtures: oval in loose AABB.

## Files

| Path | Change |
| --- | --- |
| `src/components/bubble_contour.py` | New |
| `src/components/text_segmenter.py` | Wire; remove ellipse retouch fallback |
| `src/config.py` | `bubble_mask_inset_px` |
| `tests/unit/test_bubble_contour.py` | New SC-001/SC-002 |

## Testing

- Unit: no AABB corner pixels; high coverage near inner outline.
- Existing segment / lama tests green.

## Risks

- Thin JPEG outlines: prefer no leak (empty/ink fallback) over corner bleed.
- Thought bubbles / missing outline: ink fallback.
