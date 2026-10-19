# Feature Specification: Linux LAN Bootstrap and Safe Updates

**Feature Branch**: `codex/045-linux-bootstrap-rollback`
**Created**: 2026-10-18
**Status**: Blocked-acceptance

> Linux/systemd acceptance on a clean host remains.

**Input**: Roadmap tasks T21–T22: idempotent clean Linux server bootstrap, separate staged application updates, health validation and rollback while preserving user data and downloaded components.

## User Scenarios & Testing

### User Story 1 - Install a clean LAN server (Priority: P1)

An administrator installs the packaged Linux server on a clean host, prepares its persistent directories and service account, and starts it as a managed service. Re-running the installer must preserve existing projects and components.

**Why this priority**: The LAN service needs a repeatable installation path before a safe update can exist.

**Independent Test**: Install the official Linux bundle twice in an isolated Linux VM/container, then verify service state and the health API without copying local configuration or secrets.

**Acceptance Scenarios**:

1. **Given** an extracted release bundle on a clean systemd host, **When** the administrator runs bootstrap, **Then** the app is installed under the configured root, persistent directories are created with service-user ownership, and the service starts.
2. **Given** an already installed server with projects and models, **When** bootstrap runs again, **Then** the service remains available and persistent data remains byte-for-byte unchanged.
3. **Given** deployment or health validation fails, **When** bootstrap exits, **Then** it reports the failed step and does not mark the service as ready.

### User Story 2 - Update safely and roll back (Priority: P1)

An administrator stages a new application release without replacing shared projects, settings, models, or runtime packs. The service switches to the new release only after the health check passes; otherwise the previous release is restored.

**Why this priority**: A failed update must not make an otherwise working LAN service unavailable or damage its data.

**Independent Test**: Install two test releases in a disposable Linux environment; force the candidate health check to fail and verify the old release serves the health API and all shared data is intact.

**Acceptance Scenarios**:

1. **Given** a healthy current release, **When** a valid candidate is staged and its service passes health validation, **Then** the candidate becomes active and the previous release remains available for rollback.
2. **Given** a candidate that exits or fails health validation, **When** the update finishes, **Then** the previous release is active again and its API responds healthy.
3. **Given** an update is in progress, **When** another install/update starts, **Then** it is refused without changing the active release.

### Edge Cases

- Interrupted archive extraction leaves the active release and shared directories unchanged.
- Missing systemd, required tools, malformed release metadata, or insufficient disk space produce an actionable error before switching releases.
- A failed service restart or timeout triggers rollback and checks the old service again.
- Re-running bootstrap against an existing root does not replace local secrets or overwrite project data.
- Symlinks are replaced atomically where supported; the updater must fail safely if atomic activation is unavailable.

## Requirements

### Functional Requirements

- **FR-001**: Bootstrap MUST install a supplied packaged Linux release into a versioned application directory and keep the active release separately addressable.
- **FR-002**: Bootstrap MUST create or reuse a dedicated service account and persistent data, model, and runtime directories with the minimum ownership needed by the service.
- **FR-003**: Bootstrap MUST install or update a systemd service definition and enable it to start on boot.
- **FR-004**: Bootstrap MUST be idempotent and MUST preserve existing projects, settings, downloaded models, and runtime packs on repeated runs.
- **FR-005**: Bootstrap MUST separate one-time installation and component preparation from routine application updates.
- **FR-006**: The update operation MUST validate the candidate release and stage it without modifying the active release or shared data.
- **FR-007**: The update operation MUST switch the active release only after the service starts and its health endpoint reports ready.
- **FR-008**: If candidate startup or health validation fails, the update operation MUST restore the previous active release, restart it, and verify its health.
- **FR-009**: Install and update operations MUST serialize concurrent invocations and report each failed step with a nonzero exit status.
- **FR-010**: Operators MUST be able to inspect the active and previous release versions and invoke a rollback without deleting persistent data.
- **FR-011**: Deployment scripts MUST not copy developer settings, API keys, project data, local models, or runtime caches from the build machine.

### Key Entities

- **Release**: Versioned packaged application with an executable, internal files, web assets, and a release identity.
- **Active release**: The one release selected to serve requests.
- **Persistent state**: Projects, settings, logs, downloaded models, and runtime packs that survive application updates.
- **Service health**: The result and observed version from the running LAN API.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Two consecutive bootstrap runs on a clean Linux host complete successfully and leave one active service with unchanged persistent data after the second run.
- **SC-002**: A successful update activates the candidate only after the health endpoint returns `ready=true`; the active release pointer resolves to the candidate version.
- **SC-003**: A forced failed health check restores the previous release and the previous health endpoint becomes ready within 60 seconds.
- **SC-004**: Project, settings, model, and runtime files have identical hashes before and after a failed update.
- **SC-005**: A second concurrent install/update exits without changing active-release identity.
- **SC-006**: After first-time component preparation, the clean Linux server completes one real translation request through the LAN API.

## Assumptions

- The host is Linux with systemd and standard archive, filesystem, and HTTP health-check tools.
- The administrator supplies an official packaged Linux release bundle; build-machine state is never a source of server data.
- `/opt/image-localization-tool` is the default installation root and can be overridden explicitly.
- The server service runs under a dedicated unprivileged account; privileged setup is limited to filesystem, account, and systemd operations.
- Windows staged updates remain a separate platform path and require their own acceptance run.
