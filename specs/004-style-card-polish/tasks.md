# Tasks: Style Card Polish

**Input**: `/specs/004-style-card-polish/`

## Phase 1: Spec

- [x] T001 Write spec/plan/research/data-model/quickstart
- [x] T002 Checklist requirements

## Phase 2: Warp flag

- [x] T003 Add `flag` remap in `src/components/text_warp.py` and wire `warp_image` / `build_remap`
- [x] T004 Update typesetter warp padding for `flag` if needed; UI `applyCardWarp` sets `kind: flag`
- [x] T005 Unit tests flag≠wave in `tests/unit/test_text_warp.py`

## Phase 3: Fonts

- [x] T006 `GET /api/fonts/{id}/file` in `src/app/server.py`
- [x] T007 Inject `@font-face` and option font-family in `web/js/inspector.js`

## Phase 4: Project styles on card

- [x] T008 Render style chips from `styleLibrary` on region card; apply on click
- [x] T009 Ensure `projectStyles` fetch only when UI uses it (keep fetch + chips)

## Phase 5: Verify

- [x] T010 Update `docs/PROBLEMS.md` — remove three UX sections; keep Flutter
- [x] T011 Record progress.md; converge check
