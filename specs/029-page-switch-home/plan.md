# Implementation Plan: Page Switch Home

**Branch**: `029-page-switch-home` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/029-page-switch-home/spec.md`

## Summary

Вернуть веб-поведение смены страницы: при числовом зуме новая страница стартует от верхнего края, зум сохраняется. Точка входа — `ViewerState.openPage()` вызывает новый `CanvasSession.homeForPage()`; флаг `_pinHome` доводит позицию до реального размера нового листа (включая страницы одинаковых размеров). Python не трогается.

## Technical Context

**Language/Version**: Dart 3.13.5 / Flutter stable 3.47.7
**Primary Dependencies**: SDK; без новых пакетов
**Storage**: без изменений
**Testing**: `flutter test` (юниты `viewer_state_test`), `flutter analyze`; pytest — контрольный полный прогон
**Target Platform**: Windows 10/11 x64
**Constraints**: минимальный diff; русские комментарии; координаты листа и хит-тесты не менять
**Scale/Scope**: 1 файл `apps/desktop/lib/src/state/viewer_state.dart`, 1 тестовый файл

## Constitution Check

- Pipeline v2 не тронут — PASS
- Минимальный diff — PASS (метод + флаг в `CanvasSession`, один вызов в `openPage`, тесты)
- Комментарии на русском — PASS
- Локальные данные не коммитить — PASS
- Совместимость — PASS (CLI, окно, LAN, extension не затронуты)

## Изменения

### 1. `CanvasSession` (`viewer_state.dart`)

- Поле `bool _pinHome = false;` рядом с `_verticalMargin` (веб-аналог `scrollHome`).
- Новый метод `homeForPage()`:
  - `_pendingScrollLeft/_pendingScrollTop = null` (смена страницы отменяет восстановленное смещение);
  - `clearPreviews(); clearLasso(); cursor = null;` (веб гасит черновики жестов на смене страницы);
  - `_pinHome = _zoomMode is num;` и `_recompute()`: для числового зума `_recompute` строит `ViewTransform(scale)` с `tx/ty = 0` и `clamped(...)` — «домой»; для `fit`/`fit-width` — обычный пересчёт.
- `setImageSize()`: ветка `if (_pinHome) { _pinHome = false; _recompute(); return; }` до текущей проверки режимов — перекламп по фактическому размеру новой страницы (закрывает и случай `_imageSize == size`, когда ранний `return` оставил бы старый сдвиг).
- `restoreSession()`: `_pinHome = false` — позиция из пакета приоритетнее.

### 2. `ViewerState.openPage()`

- Перед `_notify()`: `if (next != null && previous != next) session.homeForPage();` — закрытие страницы и перезагрузка той же не трогают сессию. Покрывает стрелки, PgUp/PgDn, клики рельса, шаги сцены.

## Тесты

- `test/viewer_state_test.dart`:
  - числовой зум 1.0 → `panBy(0, −400)` → `openPage('p2')`: `zoomMode == 1.0`, `scale == 1.0`, `ty == 0`;
  - тот же id: после `panBy` повторный `openPage('p2')` не сбрасывает `ty`;
  - `fit`: смена страницы сохраняет вписанный масштаб.
- Регрессии: полный `flutter test` (118+), `flutter analyze` — 0 issues.

## Project Structure

```text
specs/029-page-switch-home/{spec,plan,tasks}.md

apps/desktop/
├── lib/src/state/viewer_state.dart     # _pinHome, homeForPage, openPage
└── test/viewer_state_test.dart
```

## Converge

- `flutter analyze`, `flutter test`; `python -m pytest` (контроль, Python не тронут).
- `scripts/build-windows.ps1 -SkipModels` → `scripts/deploy-windows.ps1`; живой smoke (bootstrap).
- Живой прогон пользователем: зум → пролистать вниз → стрелка/список → новая страница сверху, масштаб сохранён.

## Complexity Tracking

| Item | Why |
|------|-----|
| `_pinHome` в `CanvasSession`, не в `ViewerState` | событие «размер листа узнан» живёт в канвасе (`setImageSize`), а смена страницы — в `ViewerState`; флаг сводит их без гонок |
