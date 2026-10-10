# Implementation Plan: Editor Session & Dual Mask Tools

**Branch**: `015-editor-session-tools`  
**Date**: 2026-10-10  
**Spec**: [spec.md](./spec.md)

## Summary

Preserve page + viewport across package save/load; add fit-width; merge brush/eraser and lasso +/− onto LMB/RMB.

## Constitution check

- Minimal diff; portable package optional `editor` field.
- Russian comments/docstrings for new helpers.
- New erase_fill stroke mode in models + segmenter.

## Files

| Path | Change |
| --- | --- |
| `web/js/state.js` | Preserve active in setProject |
| `web/js/editor_session.js` | capture/apply/normalize session |
| `web/js/viewer.js` | fit-width, dual tools, scroll restore hooks |
| `web/js/main.js` / `api.js` | save/load editor |
| `web/index.html` | UI button + tooltips, drop eraser |
| `web/js/keys.js` | drop KeyE eraser |
| `web/js/mask_draft.js` | erase_fill |
| `src/models.py` / `text_segmenter.py` | erase_fill |
| `src/app/portable_project.py` / `server.py` | pack/unpack editor |

## Testing

- `tests/js/test_editor_session.mjs`
- pytest portable editor roundtrip + apply_strokes erase_fill
