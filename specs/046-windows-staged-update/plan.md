# Implementation Plan: Windows Staged Update and Rollback

**Branch**: `codex/046-windows-staged-update` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/046-windows-staged-update/spec.md`

## Summary

Create a staged update and rollback path for the Windows portable package. Validate release metadata and required app files before activation, probe the staged sidecar with isolated data, preserve user directories during a same-volume install swap, and restore the prior version if activation or explicit rollback fails.

## Technical Context

**Language/Version**: PowerShell 5.1 for Windows lifecycle scripts; Python 3.10–3.13 for the packaged sidecar

**Primary Dependencies**: Windows PowerShell, built-in .NET file/process APIs, packaged application

**Storage**: Portable release folders, `release.json`, persistent user directories, lock and previous-release metadata beside the install root

**Testing**: PowerShell integration harness over isolated temporary install roots; Python and JavaScript regression suites

**Target Platform**: Windows 10/11 x64

**Project Type**: Desktop application distribution and update scripts

**Performance Goals**: Package health probe completes within the configured timeout; no requirement to minimize full-package copy time

**Constraints**: Active installation is never modified before a complete candidate is staged and healthy; user data survives update and rollback; scripts remain usable from PowerShell 5.1; no network access is required by the updater

**Scale/Scope**: One local portable installation and one update/rollback operation at a time

## Constitution Check

- **Pipeline v2**: Pass. The updater only starts the packaged sidecar for a health probe; it does not change image processing.
- **Minimal diff**: Pass. Add release metadata and the update scripts/tests/docs; leave the existing runtime path and Windows host unchanged.
- **Russian documentation/comments**: Pass. New comments, diagnostics, and docs are Russian; package metadata keys remain machine-readable.
- **Local data**: Pass. Tests use disposable data under an isolated temporary root; no personal files or secrets are packaged.
- **Compatibility boundaries**: Pass. Existing launch paths remain in place; the update operates on the portable root layout.

## Research Decisions

- The portable archive is the update bundle. It already contains `desktop/`, `sidecar/`, `web/`, and shared runtime assets.
- Update activation uses same-volume directory moves because the user-facing install path is fixed and Windows directory symlinks require permissions that portable users may not have.
- The staged sidecar is started with temporary data and a loopback-only health port. This checks the actual packaged executable without modifying user settings, projects, or component caches.
- The install root must not be in use by a running app process. The updater refuses early; it does not terminate user work.
- Previous releases remain beside the install root and are referenced by a small metadata file. User data is moved forward into the active root and moved back during rollback.

## Project Structure

```text
scripts/package-portable.ps1                 # add release.json and updater tools to the archive
scripts/update-windows.ps1                    # validate, stage, health-check, activate, rollback
scripts/rollback-windows.ps1                  # explicitly activate the previous release
scripts/windows-update-common.ps1             # shared validation, locks, probe, data and move helpers
docs/WINDOWS_UPDATE.md                        # user workflow and recovery instructions
tests/windows/test_update_windows.ps1         # isolated integration acceptance
specs/046-windows-staged-update/               # feature artifacts
```

**Structure Decision**: Keep the workflow in PowerShell beside existing Windows package scripts. No application settings or installer UI are added.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| A process keeps executable files open | Detect processes whose executable path is under the install root and refuse before staging changes. |
| A candidate starts only when its original path is preserved | Probe the staged folder in place and keep the stage on the same volume as the destination. |
| A failed move leaves the install path missing | Track each move and restore the recorded previous folder in a `finally` recovery path. |
| User directories are accidentally replaced by package contents | Move only the documented persistent directories from the old root and verify sentinel hashes in integration tests. |
| Previous version metadata points outside the expected directory | Resolve only relative sibling folders with the expected naming format; reject traversal and reparse points. |

## Open Questions

- None. The update input is the project’s portable Windows archive; the existing installer remains unchanged.
