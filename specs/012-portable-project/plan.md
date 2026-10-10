# Implementation Plan: Portable Project Package

**Branch**: `012-portable-project` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

## Summary

Portable `.ilt.zip` (project.json + ordered page images with `0001_` prefixes) as import/export over existing `ProjectStore`. File menu Save/Load/Close. Drag-reorder in left page list persists by rewriting `project.pages[]` order.

## Technical Context

- **Language**: Python 3.10–3.13, vanilla JS (existing web UI)
- **Packaging**: stdlib `zipfile`; images copied into ZIP; Load extracts into project `imports/`
- **Storage**: Existing `ProjectStore.project.json` `pages` array is already ordered — add `reorder_pages`
- **UI**: `web/js/pages.js` HTML5 DnD; File menu in `index.html` / `main.js` / `keys.js`
- **Dialogs**: Extend `DialogBridge` with open/save project file pickers
- **Testing**: pytest round-trip ZIP + reorder; optional thin JS/DnD coverage via existing patterns

## Constitution Check

- Pipeline v2: unchanged entry; Load restores documents, optional later re-run
- Minimal diff: new `src/app/portable_project.py`; thin store/server/UI hooks
- Russian comments/docstrings
- No secrets in package JSON
- CLI/extension/LAN surfaces unchanged

## Project Structure

```text
src/app/portable_project.py   # pack / unpack / validate
src/app/store.py              # reorder_pages
src/app/server.py             # API routes
src/app/dialogs.py + desktop  # file pickers
web/index.html, js/{main,keys,pages,state}.js, css
tests/unit/test_portable_project.py
tests/unit/test_store_reorder.py (or in store tests)
specs/012-portable-project/{research,data-model,contracts,quickstart}.md
```

## Phase 0 / 1

See [research.md](./research.md), [data-model.md](./data-model.md), [contracts/portable-project.md](./contracts/portable-project.md), [quickstart.md](./quickstart.md).

## Complexity Tracking

None — fits existing app boundaries.
