# Implementation Plan: Page Editor and Typeset

**Branch**: `003-page-editor-typeset` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

## Summary

Close PROBLEMS editor/typeset debt (no Flutter): keep prior result during re-layout, defer brush/eraser apply until «Готово», blue stroke preview, upright first layout for ordinary text, rotation about text-field center, tight balloon inset + short-reply sizing, warp/mesh correctness, style on block card, small-page upscale. Verify prior SFX/reset fixes.

## Technical Context

**Language/Version**: Python 3.10–3.13 + vanilla JS (`web/`)

**Primary Dependencies**: Existing app server, worker, typesetter, OpenCV/PIL

**Storage**: Page documents (regions, strokes) via existing store

**Testing**: pytest + targeted unit tests; manual UI for Done/preview

**Target Platform**: Desktop WebView2 window

**Project Type**: Desktop/CLI tool

**Constraints**: Minimal diff; Russian comments; pipeline v2; no Flutter; no new engine file unless needed

**Scale/Scope**: Multi-story; implement P1 first, then P2, then P3

## Constitution Check

| Gate | Status |
|------|--------|
| Pipeline v2 | PASS |
| Minimal diff | PASS — edit existing web/app/typesetter |
| Russian docs | PASS |
| Local data | PASS |
| Quality claims | PASS |
| Surfaces | PASS — shell stays WebView2 (FR-016) |

## Project Structure

```text
specs/003-page-editor-typeset/
web/js/viewer.js, state.js, main.js
web/index.html
src/components/typesetter.py
src/components/sfx_style.py / page_pipeline.py (verify)
src/app/server.py (only if defer needs server flag)
tests/unit/...
```

## Complexity Tracking

None unjustified. Small-page upscale and full warp remapping are larger; tracked as later tasks if not finished in first implement pass.
