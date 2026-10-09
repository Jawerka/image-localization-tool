# Feature Specification: Deploy Scripts + Unit CI

**Feature Branch**: `006-deploy-ci`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Tech-debt mid items: unified deploy scripts for Windows apps mirror and LAN/CT113 sync with host fallback; GitHub Actions CI running unit tests (not full e2e). Closes inventory D17 and E21. Flutter out of scope. Inno installer still optional."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Mirror a Windows build into the apps folder (Priority: P1)

A maintainer finishes a PyInstaller onedir build (or already has `dist\ImageLocalizationTool`) and runs one script that mirrors the runtime into the local apps install path used for daily launches, without copying huge models unless asked.

**Why this priority**: Today robocopy is tribal knowledge; wrong flags drop web/fonts.

**Independent Test**: Run the Windows deploy script against a temporary dest; assert exe/web/fonts layout present; models skipped by default.

**Acceptance Scenarios**:

1. **Given** a populated onedir under `dist\ImageLocalizationTool`, **When** the Windows deploy script runs, **Then** the configured apps destination receives exe, `_internal` (if present), `web`, and `fonts`.
2. **Given** default options, **When** deploy runs, **Then** `models` are not mirrored unless an explicit switch requests them.
3. **Given** missing dist, **When** deploy runs without a prior build step, **Then** the script fails with a clear message (or optionally builds first when asked).

---

### User Story 2 - Push LAN sources to CT113 with host fallback (Priority: P1)

A maintainer syncs the repo’s runtime sources (`src`, `web`, needed tests optional) to the LAN headless host and restarts the service. If the preferred DHCP address is down, the script tries the known alias/alternate IP before failing.

**Why this priority**: `.168` vs `.41` already caused failed deploys.

**Independent Test**: Dry-run or unit-level parse of host list; against real LAN when available, sync + service active. Offline CI uses mocked/dry checks.

**Acceptance Scenarios**:

1. **Given** a list of candidate hosts, **When** the first refuses SSH, **Then** the next candidate is tried.
2. **Given** a reachable host, **When** LAN deploy completes, **Then** key paths under the remote project root are updated and the service is restarted (or a dry-run reports the planned actions).
3. **Given** all hosts unreachable, **When** deploy runs, **Then** it exits non-zero with a readable error.

---

### User Story 3 - Unit tests run on every push via CI (Priority: P1)

On GitHub, a workflow installs dependencies and runs the unit suite (excluding slow / UI / external LLM / Argos-required markers) so regressions are caught without waiting for a local Playwright smoke.

**Why this priority**: No workflows in repo today.

**Independent Test**: Workflow file present; locally equivalent pytest command passes; packaging tests still pass for new scripts.

**Acceptance Scenarios**:

1. **Given** a push or PR to the default branch paths, **When** CI runs, **Then** unit tests with the agreed marker filter execute.
2. **Given** CI, **When** Playwright e2e would be needed, **Then** those jobs are not required for this feature (out of scope).
3. **Given** a failing unit test, **When** CI finishes, **Then** the workflow fails.

---

### Edge Cases

- Deploy scripts stay operable when Inno Setup is absent.
- LAN deploy must not wipe `models/`, `data/`, `venv/`, or `config.json` on the server.
- CI may use CPU-only wheels; GPU not required.
- Flutter shell out of scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A documented Windows deploy script MUST mirror the onedir build into a configurable apps destination.
- **FR-002**: A documented LAN deploy script MUST sync application sources to a remote project root with ordered host fallback and service restart.
- **FR-003**: Default Windows deploy MUST NOT copy `models` unless explicitly requested.
- **FR-004**: LAN deploy MUST NOT destroy remote `venv`, `models`, `data`, or local config by default.
- **FR-005**: Repository MUST include a GitHub Actions workflow that runs unit tests excluding slow/ui/requires_llm/requires_argos.
- **FR-006**: This feature MUST NOT replace the desktop shell with Flutter.

### Key Entities

- **Apps destination**: local folder beside/named ImageLocalizationTool used for daily exe runs.
- **LAN host candidates**: ordered SSH targets for the headless service.
- **CI unit job**: GitHub Actions job with marker-filtered pytest.

## Success Criteria *(mandatory)*

- **SC-001**: Maintainer can deploy Windows apps with one script invocation after build.
- **SC-002**: Maintainer can deploy LAN with host fallback without memorizing the current DHCP IP.
- **SC-003**: A green CI unit job exists on GitHub for the default branch workflow.
- **SC-004**: Inventory items D17 and E21 can be marked addressed for this scope.

## Assumptions

- Remote layout remains `/opt/image-localization-tool` and service `ilt.service` unless script parameters override.
- Full torch install in CI is acceptable with caching; e2e stays local/manual.
- Extension Chromium unpack path stays a separate ritual unless later scoped.
