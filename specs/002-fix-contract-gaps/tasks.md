# Tasks: Fix Contract Gaps

**Input**: Design documents from `/specs/002-fix-contract-gaps/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Focused unit tests for `_guess_type`, VLM prompt wording, and LaMa neighbor-ink flat fill.

**Organization**: Tasks grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Phase 1: Setup

- [x] T001 Confirm artefacts under `specs/002-fix-contract-gaps/` and `.specify/feature.json` points here
- [x] T002 [P] Confirm existing unit harness: `tests/unit/test_lama_inpainter.py`, `tests/unit/test_vlm_ocr.py`, `tests/unit/test_models.py`

---

## Phase 2: Foundational

- [x] T003 Confirm `TRANSLATABLE_TYPES` / `should_translate` in `src/models.py` still exclude `sign` and default-skip `sfx` (no Config change)

**Checkpoint**: Shared translation rules verified

---

## Phase 3: User Story 1 - Speech in a balloon stays dialogue (Priority: P1) MVP

**Goal**: FR-001, FR-002, FR-003, SC-001, SC-005

**Independent Test**: `_guess_type` + VLM prompt assertions

- [x] T004 [US1] Force `dialogue` for any region with `bubble_bbox` in `src/components/rapid_ocr.py` `_guess_type` (remove in-balloon short-CAPS → `sfx`)
- [x] T005 [P] [US1] Tighten type rules in `src/components/vlm_ocr.py` so balloon speech/thought is `dialogue` even when CAPS; `sfx` is onomatopoeia / stylized sound outside ordinary balloon speech
- [x] T006 [US1] Add `tests/unit/test_rapid_ocr_guess_type.py`: balloon CAPS → dialogue; free shout → sfx
- [x] T007 [P] [US1] Extend `tests/unit/test_vlm_ocr.py` to assert prompt forbids classifying balloon speech as `sfx`

**Checkpoint**: US1 independently testable

---

## Phase 4: User Story 2 - Object labels stay untranslated offline (Priority: P2)

**Goal**: FR-004, FR-005, FR-006, SC-002

- [x] T008 [US2] In `src/components/rapid_ocr.py` `_guess_type`, map short non-shout free-text to `sign`; longer free-text stays `narration`
- [x] T009 [US2] Extend `tests/unit/test_rapid_ocr_guess_type.py` for sign vs narration; assert `should_translate` skips `sign`

**Checkpoint**: US2 independently testable

---

## Phase 5: User Story 3 - Cleaning does not regrow neighbor letters (Priority: P2)

**Goal**: FR-007, SC-003

- [x] T010 [US3] Update `src/components/lama_inpainter.py` `_fill_if_uniform` to exclude high-contrast ring ink from background sample (and keep flat fill when background is clean)
- [x] T011 [US3] Add neighbor-ink case to `tests/unit/test_lama_inpainter.py` (neighbor preserved, LaMa not called when flat fill appropriate)

**Checkpoint**: US3 independently testable

---

## Phase 6: User Story 4 - PROBLEMS hygiene (Priority: P3)

**Goal**: FR-008, FR-009, SC-004

- [x] T012 [US4] Remove stale extension sections from `docs/PROBLEMS.md` (large text button, instant hover, every img >180px)
- [x] T013 [US4] Remove or mark resolved «Текст в облачке распознаётся как звук» after US1 fix; leave Flutter and other wishlist untouched

**Checkpoint**: PROBLEMS matches reality

---

## Phase 7: Polish

- [x] T014 Run pytest for touched unit files per `quickstart.md`
- [x] T015 [P] Mark T030–T032 done in `specs/001-baseline-contract/tasks.md` with pointer to `002-fix-contract-gaps`

## Dependencies

- US1 (T004–T007) before T013
- T004 before T008 (same function)
- US3 independent of US1/US2 except shared pytest polish
- US4 after US1 for dialogue section

## Parallel opportunities

- T005 ∥ T004 after T003
- T007 ∥ T006
- T010–T011 ∥ US2 after foundational
- T012 can start anytime; T013 after US1
