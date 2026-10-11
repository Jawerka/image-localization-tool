# Implementation Plan: Viewer & Canvas

**Branch**: `023-viewer` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/023-viewer/spec.md`; архитектурное решение — [spike.md](./spike.md).

## Summary

Заменить карточку-заглушку сцены из 022 настоящим просмотрщиком: рендер листа (`original|result|mask`, версии), виды «Оригинал | Результат | Сравнение» со шторкой, дискретный зум 10–200 % и панорама по решению спайка (`InteractiveViewer` → `CustomPaint` без `RepaintBoundary`), слой рамок с хитом/флагами/ручками, геометрия региона (создание/перенос/размер/поворот/warp), кисть и лассо с локальным черновиком маски, модель правок (черновик → «Готово» → PUT → перевёрстка), undo/redo по одной правке, хоткеи канваса, сессия просмотра в пакете. Инспектор 024 и диалоги 025 подключаются к той же модели документа; батч-пилюля 022 остаётся.

## Technical Context

**Language/Version**: Dart/Flutter — локально 3.44.0 / Dart 3.12; целевой pin ≥ 3.47.7 в docs до 026

**Primary Dependencies**: только SDK — `InteractiveViewer`, `CustomPaint`, `Listener`, `HardwareKeyboard`; из pubspec — `http`, `file_selector`; новых пакетов нет

**Storage**: без нового хранилища; документы страниц — `GET/PUT /api/pages/{id}`; сессия просмотра — поле `editor` в `package/save|load`

**Testing**: `flutter test` (модель документа, матрица зума/хит-тест, черновик/история; виджет-тесты канваса и пилюли), `flutter analyze`; повторный профильный прогон `tool/viewer_jank_spike.dart` после штрихов маски

**Target Platform**: Windows 10/11; сайдкар — существующий Python API

**Project Type**: desktop — Flutter host + Python sidecar

**Constraints**: `ChangeNotifier` без пакетов; содержимое сцены без `RepaintBoundary` (замер спайка: кэш слоя даёт 34–62 мс на шаг зума); русский UI; токены `web/tokens.json`; API-контракт заморожен

**Scale/Scope**: только канвас; карточки/поля инспектора — 024, модалки/полосы — 025, рельсы/страницы/батч — 022

## Spike Decision (архитектура канваса)

- Сцена: `Listener` + `InteractiveViewer(transformationController, panEnabled: false, scaleEnabled: false)` → `CustomPaint` поверх `SizedBox(imageSize)`, **без** `RepaintBoundary`; transform — только `translate+scale` (матрица прямо в контроллере).
- Оверлеи (рамки, номера, флаги, ручки, шторка, штрихи) рисуются в координатах листа с компенсацией `1/scale` для постоянного экранного размера; один пасс painter'а.
- Ctrl+колесо — дискретный шаг к точке курсора; колесо без Ctrl — перенос; панорама — средняя кнопка/пробел/«Рука»; фит/по-ширине — расчёт матрицы от вьюпорта.
- Маска: серверная картинка `BlendMode.multiply` + opacity 0.5; при неприменённом черновике — локальная (серверная маска + штрихи), без мигания.
- Хит-тест — `toScene(локальная точка)` (запас 8 px / scale), драг-машина ведёт регион от pointer-down до up.
- История: снимок документа на правку (лимит 50), коалесинг для rotate/warp-драга; штрих кисти — одна запись.

## Constitution Check

- Пайплайн v2 не тронут — PASS (только хост; API переиспользуется)
- Минимальный diff — PASS (новые файлы `ui/viewer/*` + `model/page_document.dart` + `state/viewer_state.dart`; правки `scene.dart`/`workspace_state.dart`; ничего не удаляется, кроме карточки-заглушки)
- Русский язык — PASS (docstring/комментарии на русском)
- Локальные данные — PASS (нет новых файлов вне `apps/desktop`)
- Границы совместимости — PASS (pywebview, CLI, LAN, расширение не тронуты)

## Project Structure

```text
specs/023-viewer/
├── spec.md
├── spike.md
├── plan.md
└── tasks.md

apps/desktop/lib/src/
├── model/page_document.dart         # NEW: PageDocument/Region/Stroke, normalize, clamp, blank, next id
├── state/viewer_state.dart          # NEW: документ, черновик, история, зум-матрица, инструменты, сохранение
├── state/workspace_state.dart       # + владение ViewerState, загрузка detail при выборе страницы
├── ui/viewer/viewer_pane.dart       # NEW: композиция (канвас, чипы, пилюля, стрелки, курсор кисти)
├── ui/viewer/canvas_view.dart       # NEW: Listener/InteractiveViewer, жест-машина, матрица, хит-тест
├── ui/viewer/canvas_painter.dart    # NEW: лист/шторка/маска/рамки/штрихи (1/scale компенсация)
├── ui/viewer/viewer_dock.dart       # NEW: инструменты, виды, слои, кисть, undo/redo, зум
├── ui/viewer/done_pill.dart         # NEW: перетаскиваемая пилюля «N правок · не применены»
├── ui/viewer/viewer_shortcuts.dart  # NEW: хоткеи канваса (V/R/B/P/H, 1-3, L/M, Ctrl+0/1, PgUp/PgDn, N, Del, [/], пробел)
└── ui/scene.dart                    # _EditorScene → ViewerPane

apps/desktop/test/
├── page_document_test.dart          # NEW
├── viewer_state_test.dart           # NEW
├── canvas_geometry_test.dart        # NEW
└── viewer_widget_test.dart          # NEW
```

## Complexity Tracking

| Item | Why |
|------|-----|
| Компенсация `1/scale` в painter'е | постоянный экранный размер ручек/номеров при single-paint сцене без кэш-слоя (спайк) |
| Локальный черновик маски | серверный round-trip после «Готово»; штрихи видны сразу, как в вебе (017/019) |
| История по страницам с коалесингом | «по одной правке» (014/017): штрих — запись, rotate/warp-драг — одна запись |
| Слои `boxes/mask` и режимы вида через один painter | один пасс вместо виджетов-рамок; хиты — из документа, не из виджетов |
