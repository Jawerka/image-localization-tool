# Tasks: Windows Staged Update and Rollback

**Input**: Design documents from this feature directory.

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/release-metadata.md`.

**Tests**: Integration tests are included because the update contract requires proof of preserved user data and automatic rollback.

## Phase 1: Release bundle contract

- [x] T001 Add the Windows `release.json` metadata to `scripts/package-portable.ps1` and include the update/rollback helpers in the portable archive.
- [x] T002 [P] Add release metadata and safe-path validation in `scripts/windows-update-common.ps1`.

## Phase 2: User Story 1 — Apply an update (P1)

**Goal**: A validated candidate becomes active while the closed app's persistent user data remains unchanged.

**Independent Test**: Run `tests/windows/test_update_windows.ps1 -Scenario update` against an isolated temporary installation; confirm active version, health, and preserved hashes.

- [x] T003 [P] [US1] Add isolated update-success, invalid-package, running-app, and shared-data preservation scenarios in `tests/windows/test_update_windows.ps1`.
- [x] T004 [US1] Implement single-operation locking, process-use refusal, isolated candidate health probing, same-volume staging, persistent-directory transfer, activation, and failure restoration in `scripts/update-windows.ps1` and `scripts/windows-update-common.ps1`.
- [x] T005 [US1] Document prerequisites, update command, diagnostics, and recovery behavior in `docs/WINDOWS_UPDATE.md` and `scripts/package-portable.ps1`.

## Phase 3: User Story 2 — Roll back to a previous release (P1)

**Goal**: A failed candidate or explicit rollback restores the previous working version without moving user data out of the active root.

**Independent Test**: Run `tests/windows/test_update_windows.ps1 -Scenario rollback`; verify automatic and explicit rollback, previous-pointer integrity, and unchanged data hashes.

- [x] T006 [P] [US2] Add failed-health, explicit rollback, malformed previous pointer, and rollback health failure scenarios in `tests/windows/test_update_windows.ps1`.
- [x] T007 [US2] Implement health-gated explicit release swap and reversal on failure in `scripts/rollback-windows.ps1` and `scripts/windows-update-common.ps1`.
- [x] T008 [US2] Add upgrade/downgrade/recovery instructions and error meanings in `docs/WINDOWS_UPDATE.md`.

## Phase 4: Polish and acceptance

- [x] T009 [P] Add Windows package smoke assertions for release metadata and packaged updater files in `tests/unit/test_packaging.py`.
- [x] T010 Run the isolated Windows integration scenarios and relevant packaging tests; record package size, elapsed time, and preserved-data hashes in `specs/046-windows-staged-update/research.md`.

## Dependencies

- T001 and T002 establish the release contract before T003–T005.
- US1 must create a previous-release pointer before US2 rollback can be tested.
- T006 and T007 depend on T004's shared staging and health-probe helpers.
- T009–T010 run after both stories are implemented.

## Implementation strategy

Complete the bundle contract first, then implement and validate update success/refusal, then automatic and explicit rollback. Do not change the existing active installation until the candidate health check passes.

## Phase 5: Convergence

- [x] T011 Add a `-Scenario update|rollback|all` selector to `tests/windows/test_update_windows.ps1` so the independent test commands above are executable (US1/US2 independent tests, partial).
