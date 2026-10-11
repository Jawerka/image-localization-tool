# Implementation Plan: Flutter Shell Host & Python API Sidecar

**Branch**: `021-flutter-shell-host` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/021-flutter-shell-host/spec.md`

## Summary

Python gains `--api` (headless local HTTP sidecar with `api.json` handshake and `--parent-pid` watchdog, already stubbed in `src/app/desktop.py`) plus tests. Flutter app in `apps/desktop/` becomes the host skeleton: sidecar lifecycle, handshake resolution (stdout → `api.json` poll), cookie REST client, self-written SSE reader, `ChangeNotifier` state, shell v2 chrome placeholders, host-owned single-instance IPC → `/api/drop`, dev attach mode. pywebview entry stays untouched.

## Technical Context

**Language/Version**: Python 3.10+ (sidecar); Dart/Flutter — local 3.44.0 / Dart 3.12 bootstrap, target pin **≥ 3.47.7 stable** in docs before 026
**Primary Dependencies**: Python stdlib HTTP (existing), Flutter SDK, `package:http`, `file_selector`; dev `flutter_test`, `flutter_lints`
**Storage**: `api.json`, `session.token`, `instance.json` under existing data root (`src/app/paths.py`)
**Testing**: pytest (sidecar helpers + live integration), `flutter test` (SSE parser, cookie client, handshake poll, widget smoke), `flutter analyze`
**Target Platform**: Windows 10/11 (VS 2022 Desktop C++ at build time); attach mode usable on other dev hosts
**Project Type**: desktop app — Flutter host + Python sidecar
**Constraints**: no `cookie_jar`/SSE/state packages; sidecar never writes `instance.json`; `python -m src.app` unchanged
**Scale/Scope**: lifecycle + transport + chrome skeleton only; screens in 022–025

## Constitution Check

- Pipeline v2 untouched — PASS (sidecar reuses existing server/pipeline)
- Minimal diff — PASS (new flag + new app dir; no removals)
- Russian comments/docstrings in Python — PASS; Dart code follows Flutter conventions with Russian where repo does
- Local data not committed — PASS (`apps/desktop/.gitignore`, `api.json` under data root)
- Compatibility boundaries — PASS (FR-012): CLI, pywebview window, extension, LAN unchanged

## Project Structure

```text
specs/021-flutter-shell-host/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api-sidecar.md
└── tasks.md

src/app/desktop.py            # --api, --parent-pid, api.json (exists; tests pending)
tests/unit/test_app_desktop.py

apps/desktop/
├── pubspec.yaml              # http, file_selector
├── lib/main.dart
├── lib/src/app.dart
├── lib/src/sidecar/sidecar_controller.dart
├── lib/src/sidecar/handshake.dart
├── lib/src/api/ilt_api.dart
├── lib/src/api/sse.dart
├── lib/src/state/shell_state.dart
├── lib/src/ui/shell.dart
└── test/…
```

## Complexity Tracking

| Item | Why |
|------|-----|
| Host-owned single-instance IPC (Dart `ServerSocket`) | Plan decision: Flutter owns `instance.json`; second launch forwards paths; sidecar must not write it |
| Attach mode | Keeps `python -m src.app --api` dev loop alive without spawning from IDE |
