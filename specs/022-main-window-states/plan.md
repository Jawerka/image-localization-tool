# Implementation Plan: Main Window Container Screens

**Branch**: `022-main-window-states` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/022-main-window-states/spec.md`

## Summary

Port the main window container from `web/mockups/next` (main-empty / main-editor / main-batch) to the Flutter host: a `WorkspaceState` (project, pages, recent, selection, batch, actions over the 021 REST client) plus UI regions — app bar with «Файл» menu and job pill, pages rail with real statuses and batch block, scene page-card host, inspector awaiting states, dock, status bar. Scene rendering stays a placeholder for 023; inspector interiors for 024; secondary screens and modal dialogs for 025.

## Technical Context

**Language/Version**: Dart/Flutter — local 3.44.0 / Dart 3.12 bootstrap; target pin ≥ 3.47.7 in docs before 026
**Primary Dependencies**: Flutter SDK, `package:http`, `file_selector` (both already in pubspec); no new packages
**Storage**: no new storage — state derives from `bootstrap`, collection payloads and `/api/events`
**Testing**: `flutter test` (workspace state unit tests with `MockClient`; widget tests for empty/editor/batch), `flutter analyze`
**Target Platform**: Windows 10/11 host; sidecar is the existing Python API
**Project Type**: desktop app — Flutter host + Python sidecar
**Constraints**: `ChangeNotifier` only (no state packages); Russian UI strings; tokens from `web/tokens.json`; API contract frozen (server changes only if a gap is found)
**Scale/Scope**: main window only; viewer (023), inspector (024), secondary screens/dialogs (025) excluded

## Constitution Check

- Pipeline v2 untouched — PASS (host-only changes; sidecar API reused as-is)
- Minimal diff — PASS (new UI/state files + rewrite of the 021 placeholder `shell.dart`; no removals beyond placeholders)
- Russian comments/docstrings — PASS (Dart docstrings in Russian, matching 021)
- Local data not committed — PASS (no new files outside `apps/desktop`)
- Compatibility boundaries — PASS (FR-016: pywebview, CLI, LAN, extension untouched)

## Project Structure

```text
specs/022-main-window-states/
├── plan.md
├── spec.md
└── tasks.md

apps/desktop/lib/src/
├── state/shell_state.dart       # + workspace ownership и пересылка событий
├── state/workspace_state.dart   # NEW: модели, выбор, batch, действия
├── ui/shell.dart                # пересборка: композиция регионов
├── ui/top_bar.dart              # NEW: меню «Файл», чипы, режимы, job pill
├── ui/pages_rail.dart           # NEW: список, поиск, batch-блок, подвал
├── ui/scene.dart                # NEW: дропзона/карточка страницы/stage pill
├── ui/inspector_rail.dart       # NEW: шапка + ожидающие состояния
├── ui/dock.dart                 # NEW: инструменты (disabled в batch)
├── ui/status_bar.dart           # NEW: сообщение + чипы LLM/device
├── ui/labels.dart               # NEW: RU-подписи статусов/этапов
└── ui/file_dialogs.dart         # NEW: обёртка file_selector

apps/desktop/test/
├── workspace_state_test.dart    # NEW
└── widget_test.dart             # обновить под новые экраны
```

## Complexity Tracking

| Item | Why |
|------|-----|
| PageRow merge from events | `page.updated` carries partial fields; merging keeps one rendering path for bootstrap and live updates (mirrors `web/js/state.js`) |
| Batch counters derived in state | The API has no single batch-summary call; counts derive from page statuses + job pill percent from events, same as the web client |
