# Feature Specification: LaMa Ring Tighten

**Branch**: `010-lama-ring-tighten`  
**Created**: 2026-10-09  
**Input**: Inventory item 6 — uniformity ring / mask dilation can pull in neighbor glyphs so LaMa redraws letters. Tighten ring stats and neural-mask dilation without breaking flat-fill on clean white balloons.

## User Stories

### US1 — Neighbor glyphs survive cleanup (P1)
On dense pages, cleanup must not redraw or erase adjacent letterforms when filling a balloon.

### US2 — Clean balloons still flat-fill (P1)
Isolated text on uniform white still uses flat fill (no unnecessary LaMa).

## Requirements
- FR-001: Stricter ring background filtering and/or smaller LaMa mask dilation vs prior defaults.
- FR-002: Existing unit cases for neighbor ink + white balloons remain green.
- FR-003: New regression unit covering a denser/softer neighbor case.
- FR-004: Flutter out of scope. Batch LLM out of scope.

## Success Criteria
- SC-001: Unit suite for lama_inpainter passes.
- SC-002: Inventory 6 risk reduced for the documented ring/dilation levers.
