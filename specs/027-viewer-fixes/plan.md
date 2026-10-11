# Implementation Plan: Viewer Fixes

**Branch**: `027-viewer-fixes` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/027-viewer-fixes/spec.md`

## Summary

Убрать двойной transform канваса (painter перестаёт применять матрицу — единственный владелец `InteractiveViewer`, как в `uncached`-спайке 023), сделать Space временной «Рукой» по `session.spaceDown` с корректным keyup-guard'ом, отдать `MaterialApp` тему из `buildIltTheme` (theme/darkTheme/themeMode), вернуть превью страниц в левый рельс через `GET /api/pages/{id}/image/thumb` (LRU + плейсхолдер), поднять высоты поиска (46) и «Добавить регион» (56) с parity в макетах. Режимы — только справка. Никаких правок Python-пайплайна, API-контракта и web-поверхностей.

## Technical Context

**Language/Version**: Dart 3.13.5 / Flutter stable 3.47.7 (пин 026); Python-сайдкар не меняется
**Primary Dependencies**: только SDK — `InteractiveViewer`, `CustomPaint`, `MouseRegion`, `dart:ui` кодек; новых пакетов нет
**Storage**: без изменений; `thumb.jpg` уже пишется store/worker
**Testing**: `flutter analyze`/`flutter test` (пиксельный painter-тест, Space, тема, рельс/высоты); pytest без регрессий
**Target Platform**: Windows 10/11 x64 (PerMonitorV2, logical px — см. Research в spec); вьюпорты канваса в логических пикселях
**Constraints**: минимальный diff; русские комментарии; содержимое сцены без `RepaintBoundary` (023); режимы — без кода
**Scale/Scope**: 6 правок в `apps/desktop`, 3 тестовых файла, 2 файла макетов

## Constitution Check

- Pipeline v2 не тронут — PASS (ни одной правки `src/`, `web/js`, `extension/`)
- Минимальный diff — PASS (удаление 4 строк в painter, локальные правки виджетов; один новый файл `page_thumb.dart`)
- Комментарии/docstring на русском — PASS
- Локальные данные не коммитить — PASS
- Совместимость — PASS (`python -m src.app`, `--api`, LAN, extension не затронуты)

## Исправления

### 1. Канвас: двойной transform

- `lib/src/ui/viewer/canvas_painter.dart`: в `paint()` убрать `canvas.save/translate/scale/restore`; оставить `scale = session.transform.scale` только для компенсаций `1/scale`. Docstring: «сцена в координатах листа, transform принадлежит InteractiveViewer».
- `lib/src/ui/viewer/canvas_view.dart`: комментарий уже говорит «transform применяет InteractiveViewer» — синхронизируем формулировку о единственном владельце (`_syncTransform`).
- Никаких изменений `_setCurtain`, hit-тестов, `addRegionAtViewCenter` — все они уже в координатах листа; после фикса согласованы.

### 2. Space — временная «Рука»

- `canvas_view.dart`:
  - `MouseRegion` переносится внутрь `AnimatedBuilder` (слушает `viewer`+`session`) — курсор и состав Stack перерисовываются при Space.
  - `_onPointerDown`: pan при `middle || session.spaceDown || viewer.tool == 'hand'`.
  - `_cursor()`: `session.spaceDown || tool == 'hand'` → `grab`.
  - Кружок кисти скрыт при `session.spaceDown`; ховер не ставит `session.cursor` при Space.
- `viewer_shortcuts.dart`: keyup Space сбрасывает `session.spaceDown` даже при фокусе в поле ввода (антизалипание); keydown — как сейчас, только при `!enabled`/typing игнорируется. `setTool` не вызывается — инструмент сохраняется.

### 3. Тема диалогов и оверлеев

- `lib/src/app.dart`: `MaterialApp(theme: buildIltTheme(light…), darkTheme: buildIltTheme(dark…), themeMode: switch themeName)`; платформенная яркость — `WidgetsBinding.instance.platformDispatcher.platformBrightness` (до `MediaQuery`). `Theme` в `shell.dart` остаётся (минимальный diff), значения совпадают.
- Автоматически чинит: «Неприменённые правки», настройки, сети, глоссарий, экспорт, F1, выход, worker, popup-меню, снекбары.

### 4. Превью страниц в рельсе

- `lib/src/state/workspace_state.dart`: `Future<Uint8List?> loadThumbnail(String pageId)` → `GET /api/pages/{id}/image/thumb` (`IltApi.getBytes`), null при отсутствии API/404/ошибке.
- `lib/src/ui/page_thumb.dart` (новый): статический LRU ~64 по `id|status`, `ui.instantiateImageCodec(bytes, targetWidth: 84)`, плейсхолдер (иконка/фон), `Key('pages-thumb-{id}')`, перезагрузка при смене ключа.
- `pages_rail.dart` `_PageTile`: строка ~66 px (thumb 58 + паддинги 4), миниатюра 42×58 со статус-точкой в правом нижнем углу (цвет из `statusColor`), далее номер/имя/статус/прогресс/меню. Верхняя точка-кружок из макета — внутри миниатюры.

### 5. Высоты

- `pages_rail.dart` `_Search`: `SizedBox(height: 28)` → 46; `contentPadding` оставить центральным, без `isDense`-обрезки.
- `inspector_rail.dart`: `OutlinedButton.icon` «Добавить регион» — `minimumSize: Size(0, 56)`, убрать `VisualDensity.compact`.
- Макеты `web/mockups/next`: `components-v2.css` + `.in2--tall{height:46px}` и `.b2--tall{height:56px}`; `main-editor.html` — поле поиска и кнопка с этими классами.

### 6. Режимы (без кода)

Справка: сегмент меняет `workspace.mode`; влияет на вкладку «Отчёт» (busy или mode=run). Полная семантика — отдельная фича; в 027 только фиксация в spec.

## Тесты

- `test/canvas_painter_test.dart` (новый): recorded canvas, viewport 300×300, image 400×400, zoom 0.5 → transform (tx=ty=50, scale=0.5); штрих в (200,200) — зелёный пиксель на месте, в (150,150) — нет (двойной transform дал бы обратное).
- `test/viewer_widget_test.dart`: Space → `grab`, tool прежний, кружок`viewer-brush-cursor` скрыт; keyup → вернулось.
- `test/screens_test.dart`: dark → `settings-screen` и `viewer-leave-dialog` тёмные (`Brightness.dark`, `identical(IltPalette.of, IltPalette.dark)`); light → светлые.
- `test/widget_test.dart`: `pages-thumb-{id}` в строке, `pages-search` 46; в `viewer_widget_test` — `inspector-add-region` 56.
- pytest — полный прогон, регрессий быть не должно (Python не тронут).

## Project Structure

```text
specs/027-viewer-fixes/{spec,plan,tasks}.md

apps/desktop/
├── lib/src/app.dart                          # MaterialApp theme/darkTheme/themeMode
├── lib/src/state/workspace_state.dart        # loadThumbnail
├── lib/src/ui/page_thumb.dart                # NEW: LRU-миниатюры
├── lib/src/ui/pages_rail.dart                # превью, высота строки, поиск 46
├── lib/src/ui/inspector/inspector_rail.dart  # кнопка 56
└── lib/src/ui/viewer/
    ├── canvas_painter.dart                   # -двойной transform
    ├── canvas_view.dart                      # Space-рука, MouseRegion
    └── viewer_shortcuts.dart                 # keyup Space без залипания
└── test/{canvas_painter,viewer_widget,screens,widget}_test.dart

web/mockups/next/
├── components-v2.css                         # .in2--tall, .b2--tall
└── main-editor.html                          # классы на поиске и кнопке
```

## Converge

- `flutter analyze`, `flutter test`; `python -m pytest` (полный).
- `scripts/build-windows.ps1` (Flutter + sidecar + Inno) → `scripts/deploy-windows.ps1` в `D:\Documents\apps\ImageLocalizationTool`.
- Живой прогон: «Вписать»/«По ширине», мазок под курсором, Space-рука с курсором и без смены инструмента, тёмные диалоги/оверлеи, превью и высоты в рельсе.

## Complexity Tracking

| Item | Why |
|------|-----|
| Перенос `MouseRegion` в `AnimatedBuilder` | курсор Space обязан перерисовываться от `session`, наружный region этого не делает |
| Ранний keyup Space в хоткей-хендлере | иначе зажатие с последующим фокусом в поле оставляет «руку» залипшей |
| `page_thumb.dart` с собственным LRU | миниатюр много, они живут вне `ViewerState`-кэша изображений; отдельный маленький кэш проще и не трогает сцену |
