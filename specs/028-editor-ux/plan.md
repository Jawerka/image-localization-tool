# Implementation Plan: Editor UX

**Branch**: `028-editor-ux` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/028-editor-ux/spec.md`

## Summary

Девять клиентских правок Flutter-хоста и один аддитивный ключ Python-настроек: перетаскиваемый док с персистенцией (`dock_position`), честный статус `running` из `job.progress` (паритет веба), оптимистичный `translate` с `skip_ready` и откатом, блок «Очередь» с иконочными пауза/стоп, полоска прогресса 4 px в строке, высоты 32/48 через `kFieldHeight`, превью 55×75 и строка 83, вертикальный запас канваса ¼, «Перевести всё» — только в меню кнопки. Пайплайн, API и воркер не меняются.

## Technical Context

**Language/Version**: Dart 3.13.5 / Flutter stable 3.47.7; Python 3.10+ (только `AppSettings`)
**Primary Dependencies**: только SDK — `GestureDetector`/`MouseRegion`, `ViewTransform`; новых пакетов нет
**Storage**: `settings.json` — аддитивный ключ `dock_position` (schema 1 без миграции)
**Testing**: `flutter analyze`/`flutter test` (юнит + виджет), `pytest` (`tests/unit/test_app_settings.py`)
**Target Platform**: Windows 10/11 x64; логические пиксели
**Constraints**: минимальный diff; русские комментарии; многострочные поля инспектора не трогать; дефолт `verticalMargin = 0`
**Scale/Scope**: ~14 файлов `apps/desktop`, 1 файл `src/app`, 3 файла макетов, 5 тестовых файлов

## Constitution Check

- Pipeline v2 не тронут — PASS (правка только сериализации настроек)
- Минимальный diff — PASS (локальные правки виджетов, один новый класс `ViewerDockHost`)
- Комментарии/docstring на русском — PASS
- Локальные данные не коммитить — PASS
- Совместимость — PASS (`python -m src.app`, CLI, LAN, extension не затронуты; новый ключ настроек аддитивен)

## Изменения

### 1. `dock_position` в настройках

- `src/app/settings.py`: поле `dock_position: str = "bottom"`, `_DOCK = ("top", "bottom")`, `_choice` в `_normalize`, ключ в `to_dict`. `from_dict` подхватывает поле сам (известные поля из dataclass).
- `tests/unit/test_app_settings.py`: нормализация мусора → `bottom`, round-trip `top`.

### 2. Док: перетаскивание и позиция

- `viewer_dock.dart`: `ViewerDockHost` (stateful): LayoutBuilder, rest-позиция `top: 12` / `bottom: 16`, drag ручки `viewer-dock-grip` (`Icons.drag_indicator`, курсор `grab`/`grabbing`), `Transform`/`Positioned`-сдвиг за указателем; на отпускании `|dy| > height/3` перекидывает сторону, иначе возвращает. Внутри — прежний `ViewerDock` (`viewer-dock`), получающий grip-виджет; кнопки дока не меняются.
- `shell.dart`: вместо `Positioned(bottom:16)` — `ViewerDockHost(workspace: workspace)`.
- `workspace_state.dart`: `dockAtTop` (из `_settings['dock_position']`), `setDockPosition()` — оптимистично `_settings` + `notifyListeners`, затем `PUT /api/settings` без `busyAction` (некритичная настройка, ошибка глотается).

### 3. Статусы: `job.progress`

- `workspace_state.dart`: ветка `job.progress` → `_mergeProgress(data)`: `status: 'running'`, `progress` (`progress`/`percent`), `stage`, `error: ''` через `PageRow.copyWith`; `page.updated` остаётся на `_mergePage`. Зеркало `onProgress` в `web/js/main.js:755`.

### 4. Оптимистичный translate + хоткеи

- `workspace_state.dart`: `translate()` синхронно `_markQueued` (страница — всегда; «всё» — `!isReady`), сохраняет `before = _pages`, затем `_run` с POST (`all` + `skip_ready: true`); при ошибке — `_pages = before; notifyListeners(); rethrow`.
- `viewer_shortcuts.dart`: в `control && !alt && !meta` — Ctrl+Enter (текущая страница) / Ctrl+Shift+Enter (все) при `hasProject && !busy`; проверка `_isTyping` до обработки, `document == null` не мешает «Перевести всё».

### 5. Вёртикальный запас канваса

- `view_transform.dart`: `clamped(image, viewport, {verticalMargin = 0})` — для `sh > vh` кламп `ty ∈ [vh − sh − m, m]`, `m = sh × verticalMargin`; меньше вьюпорта — центрирование как раньше.
- `viewer_state.dart` (CanvasSession): `_recompute` (pending-scroll и fixed — кламп с запасом), `zoomStep`, `panBy` передают `verticalMargin: 0.25`.

### 6. Рельс страниц

- `pages_rail.dart`: поиск 46 → `kFieldHeight`; `_BatchBlock`: «Очередь»/«Очередь на паузе», иконка `playlist_play`, кнопки-иконки `pause`/`play_arrow` и `stop` (красный) в тултипах; строка 66 → 83, `PageThumb` 55×75; полоска `minHeight: 4`, радиус 2; `_Footer` без `pages-translate-all` (счётчики, прогресс, «N проблема», «Повторить ошибки»).
- `page_thumb.dart`: 55×75, декод `targetWidth: 110`.
- `top_bar.dart`: пункт меню «Всё — перевести всё» → «Перевести всё».

### 7. Высоты контролов

- `theme.dart`: `const double kFieldHeight = 32;`
- `widgets.dart`: `IltSelect`/`IltTextField`/`IltNumberField` 28 → `kFieldHeight` (+ `textAlignVertical: center`).
- `inspector_controls.dart`: `InspectorInput` — только `minLines == 1 && maxLines == 1` → `SizedBox(height: kFieldHeight)` и центрирование; многострочные не трогаются.
- `inspector_rail.dart`: «Добавить регион» 56 → 48.
- `hotkeys_dialog.dart` поиск 28 → 32; `glossary_screen.dart` поиск и `IltSmallField` 28 → 32; `settings_screen.dart` поле API-ключа → 32; `region_style_section.dart` селект шрифта 28 → 32; `export_dialog.dart` псевдополе пути 28 → 32.

### 8. Макеты `web/mockups/next`

- `components-v2.css`: `.in2/.sel2` = 32 (модификатор `.in2--tall` удаляется), `.b2--tall` = 48, `.prow__thumb` 55×75.
- `main-editor.html`: у поиска убрать `in2--tall`; убрать кнопку «Перевести всё» из подвала; `b2--tall` остаётся на «Добавить регион» (48).
- `main-empty.html`: убрать «Перевести всё».
- `main-batch.html`: «Пакетный прогон» → «Очередь», кнопки паузы/стопа — иконочные (`ibtn`) с `aria-label`.

## Тесты

- `test/workspace_state_test.dart`: `job.progress` → `running` (status «Маска букв» не сбрасывает), «всё» помечает `queued` до ответа и шлёт `skip_ready`, ошибка POST откатывает; `setDockPosition` шлёт PUT и меняет `dockAtTop`.
- `test/canvas_geometry_test.dart`: `clamped` с `verticalMargin: 0.25` — границы запаса; дефолт 0 без изменений.
- `test/viewer_state_test.dart`: `CanvasSession.panBy` доезжает до границы запаса ¼ и не дальше (fixed zoom).
- `test/widget_test.dart`: `pages-search` = 32; нет `pages-translate-all`; после tap `top-translate` строка «в очереди» без ожидания POST; Ctrl+Enter/Ctrl+Shift+Enter шлют POST (через `host.requests`).
- `test/viewer_widget_test.dart`: `inspector-add-region` = 48; drag `viewer-dock-grip` вверх → `dockAtTop`, PUT; превью 55×75, строка 83.
- pytest: `dock_position` в `AppSettings` — полный прогон без регрессий.

## Project Structure

```text
specs/028-editor-ux/{spec,plan,tasks}.md

src/app/settings.py                             # dock_position
tests/unit/test_app_settings.py

apps/desktop/
├── lib/src/state/workspace_state.dart          # _mergeProgress, translate, dockAtTop
├── lib/src/state/viewer_state.dart             # CanvasSession verticalMargin
├── lib/src/model/view_transform.dart           # clamped(+verticalMargin)
├── lib/src/ui/theme.dart                       # kFieldHeight
├── lib/src/ui/shell.dart                       # ViewerDockHost
├── lib/src/ui/widgets.dart                     # поля 32
├── lib/src/ui/top_bar.dart                     # пункт «Перевести всё»
├── lib/src/ui/pages_rail.dart                  # Очередь, полоска 4, 83, поиск 32, footer
├── lib/src/ui/page_thumb.dart                  # 55×75
├── lib/src/ui/inspector/inspector_rail.dart    # кнопка 48
├── lib/src/ui/inspector/inspector_controls.dart# InspectorInput 32
├── lib/src/ui/inspector/region_style_section.dart
├── lib/src/ui/screens/{glossary,settings}_screen.dart
├── lib/src/ui/dialogs/{hotkeys,export_dialog}.dart
└── lib/src/ui/viewer/{viewer_dock,viewer_shortcuts}.dart
└── test/{workspace_state,canvas_geometry,viewer_state,widget,viewer_widget}_test.dart

web/mockups/next/{components-v2.css,main-editor.html,main-empty.html,main-batch.html}
```

## Converge

- `flutter analyze`, `flutter test`; `python -m pytest` (полный).
- `scripts/build-windows.ps1` → `scripts/deploy-windows.ps1`.
- Живой прогон: drag дока и перезапуск, реакция «Перевести», «Очередь», статусы на вёрстке, высоты, превью, панорама с запасом.

## Complexity Tracking

| Item | Why |
|------|-----|
| `ViewerDockHost` в `viewer_dock.dart` | держит drag-состояние рядом с доком; shell получает одну строку вместо позиции и ручки |
| `setDockPosition` без `busyAction` | позиция дока не должна блокировать кнопки и полосу ошибок |
| `_mergeProgress` отдельно от `_mergePage` | у событий разная семантика полей `status`; общий merge уже дал баг с `idle` |
