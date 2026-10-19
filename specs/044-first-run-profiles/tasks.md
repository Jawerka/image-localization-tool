---
description: "Implementation tasks for first-run profiles"
---

# Tasks: Профили первого запуска

**Input**: Design documents from `specs/044-first-run-profiles/`  
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/preparation-api.md](contracts/preparation-api.md)

## Phase 1: Setup

**Purpose**: подключить существующий UI-клиент к API coordinator-а.

- [x] T001 [P] Add preparation API wrappers in `web/js/api.js`

## Phase 2: Foundational

**Purpose**: определить профиль первого запуска и согласовать UI жизненный цикл с coordinator-ом.

- [x] T002 Add profile choices, target-language step, and server-scope explanation in `web/index.html`
- [x] T003 Add plan/state polling, start/pause/resume, and byte/disk estimate rendering in `web/js/settings.js`

**Checkpoint**: UI uses the existing preparation API; no second download flow is introduced.

## Phase 3: User Story 1 — LLM/VLM с локальным fallback (P1)

**Goal**: перед началом загрузки показать локальные ресурсы и объём; управлять подготовкой существующим coordinator-ом.

**Independent Test**: подменённый API возвращает оценку, мастер отображает ресурсы/байты, а backend профиля передаётся в plan.

### Tests for User Story 1

- [x] T004 [P] [US1] Cover preparation plan parameters and non-mutating plan request in `tests/unit/test_app_server.py`
- [x] T005 [P] [US1] Cover first-run preparation estimate and selected profile in `tests/e2e/test_ui_smoke.py`

### Implementation for User Story 1

- [x] T006 [US1] Preserve local fallback and explain local OCR/inpainting/project scope in `web/index.html` and `web/js/settings.js`

**Checkpoint**: mocked first-run flow renders the volume before any preparation start call.

## Phase 4: User Story 2 — Офлайн-профиль (P2)

**Goal**: явно проверить поддержку Argos направления и не менять настройки при отказе.

**Independent Test**: unsupported Argos planning returns an explicit error and no settings mutation or preparation start.

### Tests for User Story 2

- [x] T007 [P] [US2] Verify unsupported offline plan leaves settings unchanged in `tests/unit/test_app_server.py`
- [x] T008 [P] [US2] Verify unsupported offline pair error in `tests/unit/test_preparation.py`

### Implementation for User Story 2

- [x] T009 [US2] Gate wizard progression on a ready plan and report unsupported pair in `web/js/settings.js`

## Phase 5: Polish & Cross-Cutting Concerns

- [x] T010 [P] Document API use and first-run manual acceptance in `specs/044-first-run-profiles/contracts/preparation-api.md` and `specs/044-first-run-profiles/quickstart.md`
- [ ] T011 Run clean-profile preparation through the first real translation using `specs/044-first-run-profiles/quickstart.md`; restart persistence is already covered by unit/UI tests and the portable sidecar smoke.

## Dependencies & Execution Order

- Setup T001 precedes UI work.
- Foundational T002–T003 establish the form and coordinator lifecycle.
- US1 depends on T001–T003.
- US2 shares the UI plan lifecycle from T003 but can be independently verified at the API layer.
- T011 requires a real clean-profile model preparation and translation; it is not substituted by mocked UI tests or the headless startup smoke.

## Parallel Opportunities

- T004 and T005 target different test files and can be worked independently after the API flow is defined.
- T007 and T008 target separate API/preparation test modules.
- UI changes T002/T003 share the same flow and should remain sequential.

## Implementation Strategy

MVP is User Story 1: show the profile-specific resource plan and manage preparation with the existing coordinator. Add User Story 2 to validate offline language-pair behavior. Finish with a real clean-profile translation and restart-recovery check.

## Phase 6: Convergence

- [x] T012 [US1] Verify a persisted paused preparation is shown and resumed for the matching profile in `tests/e2e/test_ui_smoke.py` (FR-004, partial)
- [x] T013 [US1] Show a coordinator error state in the first-run preparation note and cover it in `tests/e2e/test_ui_smoke.py` (FR-004, partial)
