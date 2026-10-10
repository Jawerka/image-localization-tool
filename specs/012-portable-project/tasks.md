# Tasks: Portable Project Package

**Input**: Design documents from `/specs/012-portable-project/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Round-trip ZIP + reorder (SC-001/SC-002) in unit tests.

## Phase 1: Setup

- [x] T001 Confirm feature branch `012-portable-project` and docs under `specs/012-portable-project/`

## Phase 2: Foundational

- [x] T002 Add `reorder_pages(project_id, page_ids)` in `src/app/store.py` (permutation of existing ids)
- [x] T003 [P] Create `src/app/portable_project.py`: validate manifest, pack ZIP (`pages/0001_…`), unpack into store
- [x] T004 [P] Extend `DialogBridge` + `WebViewDialogs` in `src/app/dialogs.py` / `src/app/desktop.py` for open/save `.ilt.zip`
- [x] T005 Session package state (`package_path`, `dirty`) on `AppState` in `src/app/server.py` (or adjacent)

**Checkpoint**: Store order + pack/unpack + dialogs ready

## Phase 3: User Story 1 — Save package (P1) MVP

**Goal**: Save working project to `.ilt.zip` with JSON + ordered images

**Independent Test**: Save multi-page project; ZIP has `project.json` and `pages/0001_…`

- [x] T006 [US1] Implement pack API `POST /api/project/package/save` in `src/app/server.py`
- [x] T007 [US1] File menu Save / Save as + Ctrl+S in `web/index.html`, `web/js/main.js`, `web/js/keys.js`
- [x] T008 [US1] Unit test pack round-trip shape in `tests/unit/test_portable_project.py`

## Phase 4: User Story 2 — Load package (P1)

**Goal**: Load `.ilt.zip` into a working project

**Independent Test**: Load package; pages/order/docs match

- [x] T009 [US2] Implement `POST /api/project/package/load` (atomic fail on bad package)
- [x] T010 [US2] File menu Load project… wired to dialog + API in `web/js/main.js`
- [x] T011 [US2] Extend unit tests for load + invalid package rejection

## Phase 5: User Story 4 — Drag-reorder (P1)

**Goal**: DnD in page list; persist order; Save reflects prefixes

**Independent Test**: Reorder → save → load keeps order

- [x] T012 [US4] API `POST /api/project/reorder` + mark dirty
- [x] T013 [US4] HTML5 DnD in `web/js/pages.js` + CSS; no conflict with click/context menu
- [x] T014 [US4] Unit test reorder + pack prefixes match new order

## Phase 6: User Story 3 — Close (P2)

**Goal**: Close project; confirm if dirty

- [x] T015 [US3] `POST /api/project/close` + GET package/status
- [x] T016 [US3] File menu Close + dirty confirm in UI (`web/js/dialogs.js` / main)

## Phase 7: Polish

- [x] T017 [P] Smoke: empty project save message; ordinary ZIP still uses ingest
- [x] T018 Run unit tests for portable project + reorder
- [x] T019 Converge: append any remaining gaps to tasks if found

## Dependencies

- Setup → Foundational → US1/US2/US4 (P1) → US3 → Polish
- US4 depends on T002; Save uses T003; Load uses T003; Close uses T005 dirty

## Parallel opportunities

- T003 || T004 after T002
- T008 || T007 after T006
- T013 || T012 after foundational
