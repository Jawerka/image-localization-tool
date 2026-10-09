# Research: Page Editor and Typeset

## Decision 1: Keep last result URL while status is not ready

**Decision**: In `viewer.js` `setSrc`, when loading `result` and page status is not ready, do not call `showResultGap(true)` if a result is already displayed; keep the previous `src` until a ready status loads a new URL.

**Rationale**: Gap clears the image on every edited/running transition after brush apply.

## Decision 2: Defer stroke save/apply until Done

**Decision**: Brush/eraser strokes use `editDocument(..., { deferApply: true })` so local document updates and history work, but `scheduleSave` is skipped. «Готово» calls `commitDeferredEdits()` → `scheduleSave(0)` → existing `_put_document` + `apply_document`.

**Rationale**: Minimal change vs new server defer protocol; strokes still go through the same clean plan once committed.

## Decision 3: Preview stroke color

**Decision**: Change polyline stroke from `#ffffff` to a blue (`#2563eb`) with opacity ~0.55; retouch mask paint remains binary white/black server-side.

## Decision 4: Balloon inset ~2–3 px

**Decision**: `layout_inset_px` returns a fixed 3 px when margin is enabled for balloons (not `side * margin_ratio`).

## Decision 5: Export size after small-page upscale

**Decision**: Deferred to a later task; default when implemented: detect/layout on upscaled copy, map boxes back to original resolution for export.
