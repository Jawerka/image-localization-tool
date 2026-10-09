# Tasks: Baseline Product Contract

**Input**: Design documents from `/specs/001-baseline-contract/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Not requested as new automated suites; tasks verify the published contract against the existing codebase and record gaps.

**Organization**: Tasks are grouped by user story so each surface can be checked independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm baseline artefacts are in place for analysis and convergence

- [ ] T001 Confirm feature artefacts exist under `specs/001-baseline-contract/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/surfaces.md`)
- [ ] T002 [P] Confirm `.specify/feature.json` points at `specs/001-baseline-contract`
- [ ] T003 [P] Confirm constitution gates in `.specify/memory/constitution.md` are readable for later analysis

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared-path and quality-claim checks that every story depends on

**CRITICAL**: No user story verification can finish until this phase is complete

- [ ] T004 Verify all translation surfaces enter through `src/page_pipeline.py` rather than a parallel page processor in `src/main.py` and `src/app/`
- [ ] T005 [P] Verify RT-DETR size order handling around detector calls under `src/components/` matches `[width, height]`
- [ ] T006 [P] Verify product-facing ink-recall wording in `README.md` and `docs/BENCHMARK_RESULTS.md` stays reference-only for arbitrary pages (FR-013, SC-008)
- [ ] T007 Verify language-model API key write path keeps secrets out of settings JSON in `src/app/` (FR-010, SC-005)

**Checkpoint**: Shared-path and constitution-sensitive checks are ready

---

## Phase 3: User Story 1 - Translate a page from the command line (Priority: P1) MVP

**Goal**: Confirm CLI translation, fallbacks, and default sound-effect skipping match FR-001–FR-007

**Independent Test**: Trace CLI entry and run or review the path for one page with and without LLM availability

### Verification for User Story 1

- [ ] T008 [US1] Verify CLI entry in `src/main.py` accepts PNG/JPG/BMP/TIFF and writes a result image (FR-001, FR-007, SC-001)
- [ ] T009 [P] [US1] Verify balloon/text detection is invoked from the shared pipeline path in `src/page_pipeline.py` / `src/components/` (FR-002)
- [ ] T010 [P] [US1] Verify OCR prefers the vision LLM path and falls back to offline recognition with a warning in `src/page_pipeline.py` / `src/components/` (FR-003, SC-002)
- [ ] T011 [US1] Verify translation prefers the LLM path with glossary/speaker context and falls back to offline whole-block translation (FR-004)
- [ ] T012 [US1] Verify letter-masking and typesetting apply only to translated regions in `src/page_pipeline.py` / `src/components/` (FR-005)
- [ ] T013 [US1] Verify default sound-effect mode leaves SFX/object labels untranslated (FR-006, SC-003)

**Checkpoint**: CLI contract either holds or gaps are explicit for convergence

---

## Phase 4: User Story 2 - Review and translate pages in the desktop window (Priority: P1)

**Goal**: Confirm window project, job, settings, and export behaviour (FR-008, FR-017, FR-018)

**Independent Test**: Trace desktop entry and local HTTP project/job/export flows

### Verification for User Story 2

- [ ] T014 [US2] Verify desktop entry `src/app/` / `python -m src.app` creates or updates projects from files/folders and lists pages (FR-008, SC-004)
- [ ] T015 [P] [US2] Verify page job statuses and translate/export actions through local HTTP handlers in `src/app/` (FR-008)
- [ ] T016 [P] [US2] Verify empty-archive import refuses to create an empty project in `src/app/` (FR-017)
- [ ] T017 [US2] Verify second-launch path handoff via instance lock in `src/app/` (FR-018)
- [ ] T018 [US2] Verify export writes PNG/JPG with selected conflict rule from window export flow in `src/app/` / `web/` (SC-004)

**Checkpoint**: Window contract either holds or gaps are explicit

---

## Phase 5: User Story 3 - Translate images from the browser extension (Priority: P2)

**Goal**: Confirm pairing, hover control, and image substitution (FR-011, FR-012, FR-016)

**Independent Test**: Trace extension sources and remote translate/result contract

### Verification for User Story 3

- [ ] T019 [US3] Verify extension pairing and bearer usage against `/v1/pair` and translate routes as implemented in `extension/` and `src/app/` (FR-011, FR-012, SC-007)
- [ ] T020 [P] [US3] Verify two-second hover delay and compact icon-without-text control in `extension/` (FR-016)
- [ ] T021 [P] [US3] Verify result fetch substitutes the image and preserves original toggle in `extension/` (SC-007)
- [ ] T022 [US3] Verify Ozon host exclusion prevents content-script injection in `extension/` manifests/content script

**Checkpoint**: Extension contract either holds or gaps are explicit

---

## Phase 6: User Story 4 - Keep local UI local and remote access explicit (Priority: P2)

**Goal**: Confirm loopback UI and opt-in remote listener (FR-009, FR-015, SC-006)

**Independent Test**: Trace bind addresses, host/origin checks, and remote enablement

### Verification for User Story 4

- [ ] T023 [US4] Verify local UI server bind and host/origin guards remain loopback-only in `src/app/` (FR-009, SC-006)
- [ ] T024 [P] [US4] Verify remote listener stays off until settings/flag enablement in `src/app/` (FR-009)
- [ ] T025 [P] [US4] Verify protected `/v1` routes reject missing/invalid bearer tokens in `src/app/` (US4 acceptance)
- [ ] T026 [US4] Verify user-facing remote HTTP/firewall warning text exists in window settings copy under `web/` / docs referenced by README (FR-015)

**Checkpoint**: Access-boundary contract either holds or gaps are explicit

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Close the baseline verification loop without rewriting product code in this feature

- [ ] T027 [P] Run `/speckit-analyze` over `specs/001-baseline-contract/{spec,plan,tasks}.md` and record findings in the session report
- [ ] T028 Run `/speckit-converge` against the codebase and append only unmet contract gaps to this `tasks.md`
- [ ] T029 [P] Ensure `specs/001-baseline-contract/quickstart.md` still matches the verified surfaces after convergence notes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; blocks story completion claims
- **User Stories (Phases 3–6)**: Depend on Foundational checks; may proceed in parallel after T004–T007
- **Polish (Phase 7)**: Depends on story verification passes

### User Story Dependencies

- **US1 (P1)**: After Phase 2
- **US2 (P1)**: After Phase 2; independent of US1 for verification
- **US3 (P2)**: After Phase 2; needs remote contract awareness from US4 but can be checked on its own files
- **US4 (P2)**: After Phase 2; independent access-boundary check

### Parallel Opportunities

- T002/T003 in Setup
- T005/T006 in Foundational
- Within US1: T009/T010
- Within US2: T015/T016
- Within US3: T020/T021
- Within US4: T024/T025
- Polish T027/T029 after T028 or beside report writing

---

## Parallel Example: User Story 1

```text
Task: "Verify balloon/text detection is invoked from the shared pipeline path in src/page_pipeline.py / src/components/"
Task: "Verify OCR prefers the vision LLM path and falls back to offline recognition with a warning in src/page_pipeline.py / src/components/"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational checks
2. Complete US1 CLI verification
3. Stop and decide whether CLI gaps alone already justify remediation work

### Incremental Delivery

1. Setup + Foundational
2. US1 CLI
3. US2 Window
4. US3 Extension
5. US4 Access boundary
6. Analyze + converge report

### Notes

- These tasks verify and record; they do not authorize product rewrites inside this baseline feature
- Auto-commit hooks remain disabled for this analysis run

---

## Phase 8: Convergence

**Purpose**: Remaining unmet baseline-contract work found by comparing `spec.md` / `plan.md` / `tasks.md` to the current codebase. Appended 2026-10-09. Existing tasks above were not rewritten.

**Converged requirements**: FR-001–FR-003, FR-005, FR-007–FR-018 and SC-001, SC-002, SC-004–SC-008 hold in the current tree (shared `PagePipeline`, loopback UI, opt-in remote, keyring secret, extension hover delay/icon, Ozon exclude, ink-recall wording, empty-archive refusal, second-instance handoff, RT-DETR `[width, height]`).

- [x] T030 [US1] Stop in-balloon dialogue being classified as `sfx` in `src/components/vlm_ocr.py` (and the RapidOCR geometry heuristic in `src/components/rapid_ocr.py`) so default SFX skip no longer leaves speech untranslated (FR-004, FR-006, SC-003; closed by `specs/002-fix-contract-gaps`)
- [x] T031 [P] [US1] Keep LaMa flat-fill ring from capturing neighboring lettering in `src/components/lama_inpainter.py` so cleaned regions do not regrow adjacent glyphs (FR-005; closed by `specs/002-fix-contract-gaps`)
- [x] T032 [P] [US1] Stop RapidOCR free-text object labels becoming `narration` in `src/components/rapid_ocr.py` `_guess_type` so default skip of object labels holds on the offline path (FR-006; closed by `specs/002-fix-contract-gaps`)
