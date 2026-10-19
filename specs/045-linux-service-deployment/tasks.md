# Tasks: Linux LAN Bootstrap and Safe Updates

**Input**: Design documents from this directory.
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/release-metadata.md.

## Phase 1: Release contract and service bootstrap (US1)

- [x] T001 Add release metadata generation to `.github/workflows/release.yml` and validate it in `scripts/`.
- [x] T002 Add a systemd unit template in `deploy/ilt.service` with explicit persistent path environment and unprivileged execution.
- [x] T003 Add `scripts/install-server-linux.sh`: validate tools/privilege/release metadata; create service user and shared paths idempotently; stage immutable release; configure `current` and persistent links; install/enable/restart unit; wait for `/v1/health`; preserve existing shared state.
- [x] T004 Add tests for release metadata validation, path layout, idempotent bootstrap, and preservation of shared files in `tests/linux/test_deploy_scripts.sh`. Bash syntax passed locally; Linux execution is part of T010.
- [x] T005 Document bootstrap prerequisites, security model, and clean-install workflow in `docs/LINUX_SERVER.md`.

## Phase 2: Health-gated update and rollback (US2)

- [x] T006 Add `scripts/update-server-linux.sh`: serialize with a lock; stage and validate a candidate; atomically switch active release; restart/probe; restore the old release on failure without touching shared state.
- [x] T007 Add `scripts/rollback-server-linux.sh` using the same lock and health validation.
- [x] T008 Extend the Linux shell harness to cover successful update, forced failed-health rollback, explicit rollback, concurrent invocation, malformed metadata, and persistent-data hashes.
- [x] T009 Package installer, updater, rollback tool, unit, and release.json in `.github/workflows/release.yml`; keep existing `deploy.sh` available.
- [ ] T010 Run script tests and release workflow validation; record Linux systemd/CT113 clean-host acceptance as an external gate until run.

## Dependencies

- T001 and T002 precede bootstrap T003.
- T003 and T004 establish the shared release/root contract before T006–T008.
- T009 packages the validated files; T010 runs after all implementation tasks.
- Clean Linux systemd acceptance and one real translation remain external acceptance evidence.
