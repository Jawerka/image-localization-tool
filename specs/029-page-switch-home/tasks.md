# Tasks: 029-page-switch-home

## Spec & plan

- [x] T001 `spec.md` (US1–US2, FR-001…FR-005, веб-референс `scrollHome`/`pinScroll`) + `plan.md`

## Code

- [x] T002 `CanvasSession`: `_pinHome`, `homeForPage()`, ветка в `setImageSize()`, сброс в `restoreSession()`
- [x] T003 `ViewerState.openPage()`: `homeForPage()` при `next != null && previous != next`

## Tests

- [x] T004 `viewer_state_test.dart`: числовой зум стартует сверху (зум сохранён); тот же id не сбрасывает; `fit` остаётся вписанным

## Verify & Converge

- [x] T005 `flutter analyze` + `flutter test` (120 passed, +2 к 028)
- [x] T006 pytest полный: 398 passed, 1 skipped, 1 pre-existing (`test_text_style::test_rotated_layer_stays_on_block_center`)
- [x] T007 Сборка `build-windows.ps1 -SkipModels` → dist + setup.exe; `deploy-windows.ps1` (robocopy exit=3); живой smoke задеплоенного exe: bootstrap 1.0.0, 0 orphan-процессов

## Итог и отклонения

- Паритет с вебом: pin только для числового зума, `fit`/`fit-width` — как раньше.
- `ty = 0` без 6px-отступа веба (`--space-sm`): у Flutter своя геометрия листа.
