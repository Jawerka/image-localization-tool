# Implementation Plan: Linux LAN Bootstrap and Safe Updates

**Branch**: `codex/045-linux-bootstrap-rollback` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary

Add an idempotent systemd installation path for the packaged Linux sidecar and a separate staged updater. Releases live in versioned directories; `current` selects the active release, while data, models, runtime packs, and downloaded components live under a shared persistent root. A bounded health probe gates activation; failure restores the previous symlink and checks the rollback.

## Technical Context

**Language/Version**: POSIX shell, Python 3.10 frozen sidecar
**Primary Dependencies**: systemd, flock, tar, curl, coreutils
**Storage**: `/opt/image-localization-tool/releases`, `/opt/image-localization-tool/shared`
**Testing**: pytest for release metadata and script behavior; Ubuntu CI for shell syntax and isolated fake-root flows; disposable Linux systemd host for acceptance
**Target Platform**: Linux x86_64 LAN server
**Project Type**: packaged desktop sidecar operated as headless HTTP service
**Performance Goals**: health probe has a bounded 60 second wait; installation/update work is serialized
**Constraints**: application changes flow through pipeline v2; no developer secrets or state enter the release; service runs unprivileged; active release selection changes atomically
**Scale/Scope**: one local service root, one active release, one previous release, shared mutable data

## Constitution Check

- **Pipeline v2**: Pass. The deployment wrapper starts the packaged sidecar and does not introduce a second translation pipeline.
- **Minimal diff**: Pass. Add Linux deployment scripts, unit template, release metadata, tests, and documentation only.
- **Russian comments/docstrings**: Pass. New inline comments and shell help are Russian; systemd keys remain standard names.
- **Local data/secrets**: Pass. Shared state stays on the host and is excluded from release archives; no API keys are copied.
- **Compatibility**: Pass. Existing CLI, headless API, port, archive entry point, Windows package, and `deploy.sh` remain available.

## Research Decisions

See [research.md](research.md). The release bundle is a frozen binary, so a server virtual environment is unnecessary. The app already supports `ILT_INSTALL_ROOT`, `ILT_DATA_DIR`, and `ILT_COMPONENT_ROOT`; use these to keep mutable content outside versioned releases. `/v1/health` is unauthenticated and reports `ready` plus the API version.

## Architecture

- Installer accepts a release bundle directory and prepares a versioned copy under `releases/<version>`.
- Shared `data`, `models`, `runtime`, and `.resources` component storage are outside versioned releases. Release-local links point to shared storage; service environment variables make data/component roots explicit.
- A systemd unit runs the release executable as a dedicated unprivileged account with `--headless --remote`.
- Bootstrap prepares assets and unit, then waits for `/v1/health` to return HTTP 200 with `ready=true`.
- Updater validates metadata and payload before staging, takes an exclusive deployment lock, and records the previous release. It flips `current` only for activation, then restarts/probes. Failure restores the previous link and service.
- `rollback` explicitly selects the recorded previous release and checks health. It does not delete any release or shared data.
- Routine update does not run `--deploy all` or modify shared components; package preparation is a bootstrap operation.

## Project Structure

```text
scripts/
├── install-server-linux.sh
├── update-server-linux.sh
└── rollback-server-linux.sh
deploy/
└── ilt.service
tests/
├── unit/test_linux_deploy.py
└── linux/test_deploy_scripts.sh
docs/
└── LINUX_SERVER.md
.github/workflows/release.yml
```

`deploy.sh` remains the existing foreground launcher for extracted archives. The release workflow adds installer/update assets and `release.json` without bundling mutable state.

## Risks and Mitigations

- **Symlink resolution changes install paths**: pass explicit install/data/component roots in systemd and create release-local links for runtime and models; test those paths against frozen Linux behavior.
- **Health endpoint reports readiness before application work is possible**: keep the acceptance smoke that performs one real page translation as a separate Linux release gate.
- **Systemd start can succeed before application readiness**: poll `/v1/health` and parse `ready`, do not rely on `systemctl start` exit alone.
- **Rollback can fail too**: preserve previous release and report both candidate and rollback errors; do not remove shared data.
- **Root assumptions**: validate effective privilege and required tools before filesystem mutation; allow a test-only fake root/commands for CI without weakening production defaults.

## Rollout

First validate the scripts in Ubuntu CI and a disposable Linux systemd host. Only after clean bootstrap and forced-failure rollback pass should the LAN deployment use them. The current direct `deploy-lan.ps1` path remains separate until the new updater is accepted.
