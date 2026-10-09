# Implementation Plan: Deploy Scripts + Unit CI

**Branch**: `006-deploy-ci` | **Date**: 2026-10-09

## Technical Context

- Build: `scripts/build-windows.ps1` (ASCII, SkipInno).
- Apps path (local): `D:\Documents\apps\ImageLocalizationTool`.
- LAN: SSH to `192.168.88.41` / `.168`, root `/opt/image-localization-tool`, `ilt.service`.
- Tests: `pytest tests/unit -m "not slow and not ui and not requires_llm and not requires_argos"`.

## Constitution Check

- Minimal ops scripts; no pipeline behavior change.
- Russian comments only where new Python helpers need them; PS1 stays ASCII like build script.
- Flutter out of scope.

## Design

| Deliverable | Approach |
|-------------|----------|
| `scripts/deploy-windows.ps1` | Optional `-Build`, robocopy `/MIR` excluding `models` unless `-IncludeModels`, dest param |
| `scripts/deploy-lan.ps1` | Hosts param (default `.41`,`.168`), tar/scp of `src`+`web` (+ optional tests), restart service; `-DryRun` |
| `.github/workflows/ci.yml` | ubuntu-latest, pip cache, pytest unit with markers |
| Unit | Static checks that scripts exist and contain key switches (like packaging tests) |

## Testing

- `tests/unit/test_deploy_scripts.py` — ASCII/keys presence.
- Local: marker-filtered unit suite (already green).
- CI: workflow validates on push.
