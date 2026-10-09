# Implementation Plan: Editor Harden + Done/Mask E2E

**Branch**: `005-editor-harden-e2e` | **Date**: 2026-10-09

## Technical Context

- Inspector rebuild: `web/js/inspector.js` `renderRegions` replaces `list.innerHTML`.
- Already restored: focus field + selection, `list.scrollTop`.
- Gap: `<details class="region-card__warp">` and `__styles` always emit `open`.
- Mask draft: `web/js/viewer.js` `maskDraft` / `paintLocalMask`; «Готово» = `[data-role='apply-edits']` → `commitDeferredEdits()`.

## Constitution Check

- Pipeline untouched.
- Minimal diff: inspector UI snapshot + e2e.
- Russian comments for new non-obvious JS helpers if any.
- Flutter out of scope.

## Phase 0 — Research

See `research.md`.

## Phase 1 — Design

- Capture open state of `[data-card-details]` (or class-keyed details) before wipe; restore `open` after bind.
- Default: first paint may open warp if no prior snapshot for that region (keep current UX of expanded warp when selecting a card fresh).
- E2E: extend `tests/e2e/test_ui_smoke.py` or sibling module with brush stroke + Готово.

## Phase 2 — Touchpoints

| Area | Change |
|------|--------|
| `inspector.js` | capture/restore details open; stop unconditional `open` |
| `tests/e2e/` | mask draft + Готово; optional details-closed rebuild |
| `progress.md` | record verify |

## Testing

- Playwright UI mark `pytest.mark.ui`.
- Keep existing smoke green.
