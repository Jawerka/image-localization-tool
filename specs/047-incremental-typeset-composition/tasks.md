# Tasks: Частичная композиция текста

**Input**: Design documents from `/specs/047-incremental-typeset-composition/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`.

**Tests**: Pixel-identical output is an explicit acceptance criterion; regression tests are required before implementation.

## Phase 1: Setup

- [x] T001 [P] Add deterministic synthetic page and region builders for incremental-composition cases in `tests/unit/test_typesetter.py`.
- [x] T002 [P] Add test helpers for persisted result provenance and legacy pages in `tests/unit/test_app_store.py`.

## Phase 2: Foundational

**Goal**: Persist trustworthy metadata for a rendered result and identify which region layers a text-only edit changed.

- [x] T003 [P] Add tests for detecting typeset-changed region IDs, global reading-direction changes, and no-op documents in `tests/unit/test_app_document.py`.
- [x] T004 [P] Add tests for recording result document version, clean SHA-256, per-region bounds, and invalidating metadata when clean changes in `tests/unit/test_app_store.py`.
- [x] T005 [P] Add tests for final ink bounds from plain and transformed text layers in `tests/unit/test_typesetter.py`.
- [x] T006 Implement changed-region calculation for typeset-only document diffs in `src/app/document.py`.
- [x] T007 Implement result provenance persistence and validation in `src/app/store.py`.
- [x] T008 Track final per-region ink bounds from the composed overlay in `src/components/typesetter.py`.

## Phase 3: User Story 1 — Apply one text edit incrementally (P1)

**Goal**: Recompose only the page area affected by a text-only edit while preserving the full-render pixels.

**Independent Test**: Update one region on a ready page, verify no clean-stage call, verify the reported dirty rectangle is <=25% of page pixels, and compare every output pixel to a full render.

- [x] T009 [P] [US1] Add API tests that attach the previous document only when the prior page result is complete and current in `tests/unit/test_app_server.py`.
- [x] T010 [P] [US1] Add exact-pixel tests for cropped alpha composition and safe dirty-rectangle construction in `tests/unit/test_typesetter.py`.
- [x] T011 [US1] Pass the eligible previous document and changed region IDs to the worker job in `src/app/server.py`.
- [x] T012 [US1] Implement crop-only composition from the clean crop and new ordered overlay, with full fallback above the 25% threshold, in `src/components/typesetter.py` and `src/page_pipeline.py`.
- [x] T013 [US1] Select the incremental path only when prior document version, clean fingerprint, result image, and scale are valid; save new provenance after a fresh commit in `src/app/worker.py`.
- [x] T014 [US1] Add worker regression coverage for incremental selection, unchanged clean-stage counts, and stale-version refusal in `tests/unit/test_app_worker.py`.

## Phase 4: User Story 2 — Preserve complex and legacy pages (P1)

**Goal**: Keep transformed, overlapping, stale, scaled, and pre-metadata pages pixel-correct by expanding the dirty area or using full composition.

**Independent Test**: Compare incremental/fallback output against full rendering for moved text, rotation, perspective, mesh v2, overlapping regions, and missing/mismatched provenance.

- [x] T015 [P] [US2] Add pixel-identity tests for moved text, rotations, perspective, and mesh v2 old/new bounds in `tests/unit/test_typesetter.py`.
- [x] T016 [P] [US2] Add tests for overlapping bubble invalidation and empty/non-empty translation transitions in `tests/unit/test_typesetter.py`.
- [x] T017 [US2] Add fallback tests for missing metadata, changed clean fingerprint, scaled layout, large dirty area, and direction changes in `tests/integration/test_page_pipeline.py`.
- [x] T018 [US2] Ensure legacy result artifacts and portable imports without provenance always select full composition in `src/app/store.py` and `src/app/worker.py`.

## Phase 5: Polish and acceptance

- [x] T019 [P] Add end-to-end API/worker pixel-identity coverage for a real page document edit in `tests/integration/test_page_pipeline.py`.
- [x] T020 Run the focused and full regression suites and record dirty-area ratios, before/after composition timings, and fallback counts in `specs/047-incremental-typeset-composition/research.md`.

## Dependencies

- T003–T008 establish region diffs and trustworthy render metadata.
- US1 depends on the foundational result provenance and region bounds.
- US2 depends on US1's incremental path and full-render fallback.
- T019–T020 run after both stories.

## Parallel Opportunities

- T003, T004, and T005 add tests in separate files and can be developed independently.
- T006, T007, and T008 modify separate modules after their corresponding tests exist.
- T009 and T010 add independent US1 tests before the API/renderer changes.
- T015 and T016 add independent US2 renderer tests.

## Implementation Strategy

Build and validate provenance first. Then enable the P1 single-region path with exact pixel comparison, followed by complex-overlap and legacy fallbacks. Keep the existing full render as the acceptance oracle and fallback. Run focused tests during each phase, then the full regression suites.
