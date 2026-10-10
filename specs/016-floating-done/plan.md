# Implementation Plan: Floating Done Chip

**Branch**: `016-floating-done` | **Spec**: [spec.md](./spec.md)

## Approach

- Pure helpers in `web/js/apply_chip.js` (clamp, snap, threshold).
- DOM chip in `stage-host`; CSS mirror of `.frame__progress` at top.
- `initApplyChip({ onCommit })` from main; visibility still driven by `deferredApply` in render.

## Files

| Path | Change |
| --- | --- |
| `web/index.html` | Move button to stage-host |
| `web/css/editor.css` | `.frame__apply` styles |
| `web/js/apply_chip.js` | Logic + drag wiring |
| `web/js/main.js` | Wire init; drop toolbar click |
| `tests/js/test_apply_chip.mjs` | Unit tests |
