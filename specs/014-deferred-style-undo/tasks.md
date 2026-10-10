# Tasks: Deferred Style Edits & Stepwise Undo

## Phase 1 — Spec

- [x] T001 Create `specs/014-deferred-style-undo/` (spec/plan/research/…)
- [x] T002 Branch `014-deferred-style-undo`

## Phase 2 — State

- [x] T003 Sticky defer + `deferredBaselineKey` in `web/js/state.js`
- [x] T004 `undo`/`redo` respect baseline; no save while deferred

## Phase 3 — UI callers

- [x] T005 Viewer: remove `coalesce: "stroke"` on stroke/lasso
- [x] T006 Inspector: `deferApply: true` on style/translation edits

## Phase 4 — Tests

- [x] T007 Node tests: N strokes → N undos; style sets deferred; undo without save while pending
- [x] T008 Mark tasks complete

## Dependencies

T003 → T004 → T005/T006 → T007
