# Implementation Plan: Secondary Screens & Dialogs

**Branch**: `025-secondary-screens` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/025-secondary-screens/spec.md`

## Summary

Add the secondary layer over the 022 shell: full-window overlays (settings with a nine-section draft form, glossary table, remote access, first-run wizard), modals (export, hotkeys, exit confirmation, worker failure) and the state/actions behind them. Two small server gap-fixes: `run_api` starts LAN when `settings.remote_enabled` is set, and `/api/dialog/directory` accepts an explicit host-picked `path` (the `--api` dialog bridge is a no-op). Everything else is host-side Flutter with `ChangeNotifier`.

## Technical Context

**Language/Version**: Dart/Flutter — local 3.44.0 / Dart 3.12 bootstrap; target pin ≥ 3.47.7 before 026
**Primary Dependencies**: Flutter SDK, `package:http`, `file_selector`; no new packages
**Storage**: existing settings/project/queue files via API; host keeps drafts in memory only
**Testing**: `flutter test` (state tests with `MockClient`, widget tests per screen/dialog), `flutter analyze`; pytest for the two server gap-fixes
**Target Platform**: Windows 10/11 host; Python sidecar
**Constraints**: `ChangeNotifier` only; mockup structure and Russian strings; tokens from `web/tokens.json`; server contract frozen except FR-015
**Scale/Scope**: settings, glossary, export, first-run, remote, hotkeys/exit/worker dialogs; style/sfx → 024

## Constitution Check

- Pipeline v2 untouched — PASS (server changes are startup/dialog plumbing only)
- Minimal diff — PASS (new screens/state files + small edits to shell/state/server)
- Russian comments/docstrings — PASS
- Local data not committed — PASS
- Compatibility boundaries — PASS (`run_api` change mirrors window-mode semantics; headless untouched)

## Project Structure

```text
specs/025-secondary-screens/
├── plan.md
├── spec.md
└── tasks.md

src/app/desktop.py               # run_api: start_remote(force=args.remote)
src/app/server.py                # _dialog_directory(state, body): explicit path
tests/unit/test_app_desktop.py   # + explicit-path / remote-settings tests

apps/desktop/lib/src/
├── state/secondary_state.dart   # NEW: модели, удалёнка, глоссарий, экспорт-опции
├── state/workspace_state.dart   # + settings, updateSettings, preview
├── state/shell_state.dart       # + overlays, exit request, worker failure
├── ui/screens/settings_screen.dart
├── ui/screens/glossary_screen.dart
├── ui/screens/remote_screen.dart
├── ui/screens/first_run_screen.dart
├── ui/dialogs/export_dialog.dart
├── ui/dialogs/hotkeys_dialog.dart
├── ui/dialogs/exit_dialog.dart
├── ui/dialogs/worker_dialog.dart
├── ui/platform.dart             # NEW: открыть путь/папку/лог
├── ui/top_bar.dart              # + пункты меню и шестерёнка
└── ui/shell.dart                # + хоткеи и оверлеи

apps/desktop/test/
├── secondary_state_test.dart    # NEW
├── screens_test.dart            # NEW
└── shell_state_test.dart        # + exit request
```

## Complexity Tracking

| Item | Why |
|------|-----|
| Settings preview without saving | Mockup requires live theme/scale preview; `WorkspaceState.previewSettings` overrides getters until apply/cancel |
| Exit request via completer | `AppLifecycleListener.onExitRequested` must await the user's dialog choice; `ShellState.confirmExit` gates on `busy` and resolves from the UI |
| Explicit export folder path | `--api` has no native dialogs; the host picks via `file_selector` and registers the path through the existing endpoint (FR-015) |
