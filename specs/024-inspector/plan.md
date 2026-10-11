# Implementation Plan: Inspector

**Branch**: `024-inspector` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/024-inspector/spec.md`; поведение — `web/js/inspector.js`, структура — `web/mockups/next/{main-editor,style,sfx,batch-run}.html`.

## Summary

Заменить заглушку правого рельса полноценным инспектором: карточки регионов со синхронизацией выделения с канвасом 023, тексты с автосохранением (debounce/коалесинг/`translation_locked`), секция стиля (шрифты/кегль/чернила/цвета/обводка/warp) с предпросмотром на канвасе (`preview-region`), действия региона (`action`, `skip`, `delete`), карточка звука (`sfx-style`), вкладка «Страница» (факты, reset, retranslate) и условная вкладка «Отчёт» прогона. Состояние — расширение `ViewerState` (документ/черновик/история/409 из 023) + проброс из `WorkspaceState`; UI — новый каталог `ui/inspector/`. Новых пакетов и серверных изменений нет, кроме gap-fix при прогоне.

## Technical Context

**Language/Version**: Dart/Flutter — локально 3.44.0 / Dart 3.12; целевой pin ≥ 3.47.7 в docs до 026

**Primary Dependencies**: только SDK — `FontLoader` (`ui`/`services`), `TextField`/`TextEditingController`, `AnimatedBuilder`; из pubspec — `http`, `file_selector`; новых пакетов нет

**Storage**: без нового хранилища; документы — существующие `/api/pages/{id}` + `/document`; стили проекта — `GET/PUT /api/project/styles` на сервере

**Testing**: `flutter test` (state: автосохранение/коалесинг/locked/clipboard/пресеты/клампы/действия/sfx/reset/шрифты/стили/preview; widget: карточки/поля/вкладки/отчёт; painter: позиция превью), `flutter analyze`; живой smoke `tool/` против сайдкара

**Target Platform**: Windows 10/11; сайдкар — существующий Python API

**Project Type**: desktop — Flutter host + Python sidecar

**Constraints**: `ChangeNotifier` без пакетов; правки — через `ViewerState.editDocument` (023): текст — немедленно (debounce 500, коалесинг), стиль — deferred до «Готово»; выделение — один id; русский UI; токены `web/tokens.json`; API-контракт заморожен (кроме gap-fix)

**Scale/Scope**: только правый рельс и слой превью канваса; канвас/зум/маска/батч-каркас — 023/022; экраны/диалоги — 025

## Constitution Check

- Пайплайн v2 не тронут — PASS (только хост; API переиспользуется)
- Минимальный diff — PASS (новый каталог `ui/inspector/` + расширение `ViewerState`; правки `shell.dart`, `canvas_painter.dart`, `viewer_shortcuts.dart`; старый `inspector_rail.dart` заменяется)
- Русский язык — PASS (docstring/комментарии на русском)
- Локальные данные — PASS (нет новых файлов вне `apps/desktop`)
- Границы совместимости — PASS (pywebview, CLI, LAN, расширение не тронуты)

## Архитектура инспектора

- **Вкладки**: `text | page | report`; `report` виден при `workspace.busy || workspace.mode == 'run'`; при batch вкладка `text` показывает ожидание (022).
- **Карточки**: одна колонка, выбранная карточка развёрнута; автоскролл к выбранной при смене id (Scrollable.ensureVisible / GlobalKey); флаги и номера — из документа, без виджетов канваса.
- **Поля текста**: `TextEditingController` на карточке (StatefulWidget), инициализация из документа, автосинк при внешнем обновлении (version/контент) без сброса каретки; «Сохраняем…/Автосохранено» — от `viewer.isDirty(pageId)`.
- **Стиль**: переиспользует `editDocument(deferApply: true)`; пресеты — зеркало `applyCardWarp`; «Нет» сбрасывает quad/mesh; bend — коалесинг `warp:<id>`.
- **Стили проекта**: `styleLibrary` в `ViewerState`, загрузка при смене проекта (`WorkspaceState.applyBootstrap/applyCollection` → `viewer.ensureStyles(projectId)`), сохранение — PUT полного списка.
- **Шрифты**: `ensureFonts()` при первом открытии рельса; `GET /api/fonts` + по каждому id `GET /api/fonts/{id}/file` → `FontLoader('ilt-font-<id>')`; ошибки — тихо, образцы без шрифта.
- **Предпросмотр**: `schedulePreview()` (debounce 400, токен) на смене выделения/стиля; результат — `ui.Image` + смещение; painter рисует поверх результата в координатах листа; очистка при снятии выделения/смене страницы/`detach`.
- **Действия**: `regionAction` (pendingAction в состоянии, ошибка — полосой), `toggleSkip` (немедленный save), `delete` (черновик), `restyleSfx` (commit черновика → POST → force-перечитка), `resetPage` (POST → clearHistory → перечитка).
- **Отчёт**: производный от `WorkspaceState.batch/paused/errorText→pages`; действия — `retryErrors`, «Открыть лог» через колбэк оболочки (`ShellState.logPath` + `openPath`).

## Project Structure

```text
specs/024-inspector/
├── spec.md
├── plan.md
└── tasks.md

apps/desktop/lib/src/
├── state/viewer_state.dart            # + инспектор-API: текст/стиль/действия/sfx/preview/шрифты/стили проекта, счётчик черновика
├── state/workspace_state.dart         # + ensureStyles при bootstrap/collection (проектный стиль)
├── ui/inspector/inspector_rail.dart   # NEW (замена ui/inspector_rail.dart): вкладки, шапка, состояния
├── ui/inspector/region_card.dart      # NEW: карточка (свёрнутая/развёрнутая, тексты, действия, флаги)
├── ui/inspector/region_style_section.dart # NEW: шрифт/кегль/чернила/цвета/warp/стили проекта
├── ui/inspector/sfx_section.dart      # NEW: карточка звука
├── ui/inspector/page_facts.dart       # NEW: вкладка «Страница»
├── ui/inspector/run_report.dart       # NEW: «Отчёт» прогона
├── ui/inspector/inspector_controls.dart # NEW: мелкие контролы (метка, мини-кнопка, чип, поле)
├── ui/viewer/canvas_painter.dart      # + слой предпросмотра стиля
├── ui/viewer/viewer_shortcuts.dart    # + Ctrl+Shift+C/V (стиль), не трогая ввод
├── ui/shell.dart                      # + импорт инспектора, колбэк «Открыть лог»
└── ui/viewer/done_pill.dart           # (счётчик неприменённых — через ViewerState.editCount)

apps/desktop/test/
├── inspector_state_test.dart          # NEW
└── inspector_widget_test.dart         # NEW
```

## Complexity Tracking

| Item | Why |
|------|-----|
| Автосохранение текста отдельно от deferred | веб-паритет: текст применяется сразу (debounce 500), стиль ждёт «Готово»; пилюля считает только черновик |
| Слой preview-картинки в painter | канвас 023 рисует одним `CustomPaint` без `RepaintBoundary`; превью — ещё один `drawImageRect` того же пасса |
| `FontLoader` вместо @font-face | Flutter-эквивалент инжекции шрифтов веба; тихий фолбэк при ошибке |
| Автоскролл к выбранной карточке | синхронизация канвас → рельс (US1); `GlobalKey` + `Scrollable.ensureVisible` |
| Счётчик «N правок» только для черновика | 023 считал историю целиком; текстовые автосохранения не должны попадать в «не применены» |
