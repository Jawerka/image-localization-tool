# Implementation Plan: Style Card Polish

**Branch**: `004-style-card-polish` | **Date**: 2026-10-09

## Technical Context

- Stack: existing WebView2 UI (`web/js/inspector.js`), `text_warp.py`, HTTP `/api/project/styles`, `/api/fonts`.
- Gap: styles loaded into `styleLibrary` with no UI; fonts are plain `<option>`; flag→wave.

## Constitution Check

- Pipeline v2 untouched for layout path except warp kind `flag`.
- Minimal diff: inspector + text_warp + small font file route.
- Russian comments/docstrings for new Python.
- Flutter not in scope (FR-005).

## Phase 0 — Research

See `research.md`.

## Phase 1 — Design

- `flag` remap: vertical displacement vs X only (classic flag).
- `@font-face` via `GET /api/fonts/{id}/file`.
- Style chips on region card under warp `details` or adjacent `details` «Стили проекта».

## Phase 2 — Implementation touchpoints

| Area | Change |
|------|--------|
| `text_warp.py` | `flag` kind + `_map_flag` |
| `typesetter.py` | padding estimate for `flag` like `wave` if needed |
| `server.py` | font file route |
| `api.js` | `fontFileUrl(id)` helper |
| `inspector.js` | chips, apply style, font-face injection, flag kind |
| tests | warp flag≠wave; optional font route smoke |

## Testing

- Unit: `test_text_warp.py` flag vs wave.
- Manual: chips + font select faces.
