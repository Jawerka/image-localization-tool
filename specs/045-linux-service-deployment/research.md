# Research: Linux LAN Bootstrap and Safe Updates

**Date**: 2026-10-18

## Current packaging and runtime

- `.github/workflows/release.yml` assembles the Linux tarball with the frozen `ImageLocalizationTool`, `_internal`, web assets, optional fonts, and empty `data/`, `models/`, and `runtime/` placeholders. It currently installs only `deploy.sh`.
- `scripts/deploy-server.sh` runs `--deploy all` and then starts `--headless --remote` in the foreground. It does not create a systemd unit, service account, versioned release, or health-gated update.
- `src/utils/paths.py` supports `ILT_INSTALL_ROOT` and `ILT_COMPONENT_ROOT`; `src/app/paths.py` supports `ILT_DATA_DIR`. On Linux, runtime packs are under the install root and model/component catalogs use the component root.
- `GET /v1/health` is unauthenticated and returns `version` and `ready`; this is a better readiness signal than `systemctl start` alone.

## Decisions

1. Use the already frozen release artifact: no Python virtual environment or dependency installation is needed on the target host.
2. Keep immutable release files under `releases/<version>` and mutable content under `shared/`. Point the active symlink at one version. Do not extract over the active directory.
3. Use explicit `ILT_INSTALL_ROOT`, `ILT_DATA_DIR`, and `ILT_COMPONENT_ROOT` values in the service unit, with `models`, `runtime`, and component store pointing at shared storage. These preserve the path contracts already supported by the application.
4. Install as a dedicated service user. Privileged actions are limited to creating the user, preparing installation/shared directories, installing the unit, and managing the service.
5. Require a health response with HTTP 200 and JSON `ready=true`; service-manager success alone is insufficient. systemd `Type=exec` gives an execution failure on a missing/unlaunchable executable, while the health poll checks application readiness.
6. Serialize operations using an exclusive lock. Keep at least the candidate and previous release. Do not remove old releases as part of activation or rollback.
7. Routine update installs only application files and release metadata. Bootstrap may prepare models and runtime packs; updates must not silently download or rewrite shared components.

## Failure behavior

- Reject malformed release metadata, non-versioned directories, missing executable, missing required tools, and insufficient privileges before changing `current`.
- Extract into a temporary staging directory on the same filesystem as `releases`, validate expected files, then rename into a version directory.
- Create a temporary symlink beside `current` and rename it over `current` to avoid an intermediate missing link.
- If candidate restart or health check fails, restore `current` to the saved previous target, restart the old unit, and confirm health. Preserve the candidate for diagnosis; return nonzero.
- An explicit rollback follows the same lock, link, restart, and health-check flow.

## Source

- [systemd.service manual](https://www.freedesktop.org/software/systemd/man/262/systemd.service.html): `Type=exec` catches executable invocation failures; restart and process semantics informed the unit template.
- Project source: `.github/workflows/release.yml`, `scripts/deploy-server.sh`, `src/utils/paths.py`, `src/app/paths.py`, `src/app/remote.py`.

## Validation limits

No Linux systemd host is available in the current Windows worktree. Script-level and Ubuntu CI checks can validate packaging and controlled fake-root behavior, but they cannot prove systemd activation, filesystem semantics on the target filesystem, or a real translation on CT113. Those remain explicit acceptance gates.
