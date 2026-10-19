# Research: Windows staged update

Дата: 2026-10-18.

## Existing distribution layout

- `scripts/package-portable.ps1` creates a zip from `dist/ImageLocalizationTool` and keeps the Flutter host (`desktop/`), sidecar (`sidecar/`), web UI, fonts, and required assets.
- The archive contains `release.json` (schema 1, version, platform, and expected entry points) plus the Windows updater and rollback scripts. The ZIP retains its single top-level directory; the updater normalizes that directory into same-volume staging before validation.
- `scripts/deploy-windows.ps1` is a developer deployment helper. It mirrors build output with `robocopy /MIR` while protecting selected user directories; it is not a transactional end-user updater.
- The packaged sidecar supports `--headless --remote`; `GET /v1/health` returns JSON with `ready` and `version`.
- `ILT_DATA_DIR` and `ILT_COMPONENT_ROOT` allow an isolated health probe without using the active install's projects or models.

## Decisions

1. Add `release.json` to the portable zip with schema, version, platform, and expected entry points. Reject malformed metadata and missing required files before copying.
2. Extract/copy a candidate into a unique sibling staging directory on the same volume as the install. This avoids cross-volume move behavior at activation.
3. Probe the candidate sidecar with an isolated temporary `ILT_DATA_DIR`, isolated component root, loopback binding, and a free port. Stop the probe process tree before activation.
4. Refuse updates while any process image path is inside the active install root. Do not close or kill user application processes.
5. Move the active install to a unique previous-release folder, move persistent folders into the candidate, and move the candidate into the fixed active path. If a move fails, move persistent folders back and restore the previous install.
6. Keep one explicit `previous.json` pointer to the last successfully active release folder. Older previous folders are retained; the updater does not delete user files or old releases automatically.
7. Explicit rollback swaps the active app files and previous release while keeping persistent directories at the active path. The swap is reversed if the previous candidate fails its health probe.

## Verification boundaries

- PowerShell filesystem integration uses a temporary installation root and real packaged sidecar where available.
- A failing candidate is represented by a valid PE executable that exits before opening the health endpoint.
- Clean Windows installer GUI acceptance and release-download network scenarios remain release checks; the local updater harness does not prove them.

## Local Windows verification

- Built `dist/ImageLocalizationTool-1.0.2-windows-x64-portable.zip`: 522,953,571 bytes (498.7 MiB). Inspected the final ZIP and confirmed `release.json`, `update-windows.ps1`, `rollback-windows.ps1`, and `windows-update-common.ps1`; packaging assertions passed (28 tests).
- Ran `tests/windows/test_update_windows.ps1 -Scenario all` on Windows PowerShell: migration from a legacy install without `release.json`, update from the shipped ZIP format, automatic restoration after post-activation health failure, explicit rollback, failed candidate/rollback health, malformed metadata, malformed and traversal previous pointers, active lock, running-process refusal, and persistent-data hash checks all passed in 26.6 seconds. The documented `update` (15.2 sec) and `rollback` (22.9 sec) selections also passed independently.
- Seven persistent fixture files were checked after successful update, successful rollback, and each refusal. Aggregate SHA-256 of the sorted relative-path/hash manifest: `3b828aaac6d1fc50b7017726a14351e0d7699b22d108bd0be60a299e8982f2f5`.
- The harness uses an isolated temporary install and removes it on completion. It does not install or update the user's deployed application. Linux updater execution and clean-machine installer GUI acceptance remain external checks.
