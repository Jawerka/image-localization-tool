# Implementation Plan: Deferred Style Edits & Stepwise Undo

**Branch**: `014-deferred-style-undo`  
**Date**: 2026-10-10  
**Spec**: [spec.md](./spec.md)

## Summary

Unify mask and inspector style edits under a sticky deferred session gated by Done; fix history so each completed stroke (and each logical style change) is its own undo step without server apply until Done.

## Constitution check

- Frontend-only behavior in `web/js`; no new models.
- Minimal diff; Russian comments/docstrings where added.
- Existing leave-page confirm dialog reused.

## Technical Context

**Language/Version**: JavaScript (ES modules) in `web/js`  
**Testing**: Node unit tests under `tests/js` (and/or small pure helpers)  
**Target Platform**: Desktop WebView app  
**Project Type**: desktop-app + static web UI  

## Technical approach

1. **Baseline key** (`deferredBaselineKey`) set when entering deferred; cleared on commit/discard.
2. **`editDocument`**: `defer = options.deferApply || state.deferredApply` → update document + pendingBody, no `scheduleSave`.
3. **`undo`/`redo`**: restore snapshot; `deferredApply = contentKey(doc) !== baseline`; if deferred → pendingBody only; else scheduleSave as today.
4. **Viewer**: remove `coalesce: "stroke"` from stroke/lasso commits; keep `deferApply: true`.
5. **Inspector**: `deferApply: true` on style/translation `editDocument` calls; keep field-level coalesce for sliders.
6. **Tests**: stepwise undo count; deferred undo does not call save; style sets deferredApply.

## Files

| Path | Change |
| --- | --- |
| `web/js/state.js` | Sticky defer, baseline, undo/redo without save while pending |
| `web/js/viewer.js` | Drop stroke coalesce |
| `web/js/inspector.js` | deferApply on style edits |
| `tests/js/test_deferred_edits.mjs` | New unit coverage |

## Testing

- Node tests for history/defer helpers or state behavior via extracted pure functions if needed.
- Manual: paint 3 strokes, Ctrl+Z stepwise; change font, Done applies both.

## Risks

- Geometry edits during sticky defer delay box persistence until Done — intentional per spec.
- Preview API during deferred: do not putDocument until Done.
