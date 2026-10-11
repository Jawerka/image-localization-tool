# Tasks: 024-inspector

## Spec & plan

- [x] T001 `spec.md` (US1–US6) + `plan.md` (границы с 022/023/025, режимы инспектора)

## State

- [x] T002 `viewer_state.dart`: инспектор-API текста (`setRegionText/Translation/Speaker/Type` — debounce 500, коалесинг, `translation_locked`), счётчик черновика (`editCount` только неприменённые), вкладка/шрифты/стили/preview-поля
- [x] T003 `viewer_state.dart`: стиль (`patchRegionStyle`, кегль override + кламп настроек, чернила, `resetRegionStyle`, warp-пресеты/bend), clipboard (`copyStyle/pasteStyle`), `applyProjectStyle`
- [x] T004 `viewer_state.dart`: действия (`regionAction` + pendingAction, `toggleSkip` немедленно, `deleteRegion`), sfx (`restyleSfx`: commit → POST → force-перечитка), страница (`resetPage`, `reloadDetail(force)`), отмена гонок
- [x] T005 `viewer_state.dart`: `ensureFonts` (`/api/fonts` + `FontLoader`) и `ensureStyles(projectId)` (`/api/project/styles`), `saveProjectStyle`; вызов из `workspace_state.dart` при bootstrap/collection
- [x] T006 `viewer_state.dart`: `scheduleStylePreview` (debounce 400, токен), декод PNG + смещение, очистка при снятии выделения/смене страницы/`detach`

## UI

- [x] T007 `ui/inspector/inspector_controls.dart` + `inspector_rail.dart`: шапка со стрелками/счётчиком, вкладки (Текст/Страница/Отчёт), ожидающие состояния 022, автоскролл к выбранной карточке (замена `ui/inspector_rail.dart`, импорт в `shell.dart`)
- [x] T008 `ui/inspector/region_card.dart`: свёрнутая/развёрнутая карточка, флаги, превью, поля «Перевод/Оригинал/Тип/Говорящий», чип автосохранения, «Добавить регион»/«Следующая проблема», действия, nudge-пад
- [x] T009 `ui/inspector/region_style_section.dart`: шрифт (+образец/навигация), кегль, ПРОПИСНЫЕ, чернила, цвета, толщина, warps, сброс, стили проекта, копировать/вставить
- [x] T010 `ui/inspector/sfx_section.dart`: чип «распознан как звук», замена, подобранный стиль, «Подобрать заново»/«Рамка», «Почему звук», «Другие звуки страницы»
- [x] T011 `ui/inspector/page_facts.dart` + `run_report.dart`: факты/тайминги/предупреждения + retranslate/reset; отчёт (счётчики, пауза, ошибка, retry/log, чек-лист)
- [x] T012 `canvas_painter.dart` (слой preview) + `viewer_shortcuts.dart` (Ctrl+Shift+C/V) + `shell.dart` (колбэк «Открыть лог», `ILT`-стиль кнопок)

## Tests & CI

- [x] T013 `inspector_state_test.dart`: текст (debounce/коалесинг/locked/черновик), стиль (клампы/пресеты/clipboard/стили проекта), действия/sfx/reset, шрифты, preview (токены/очистка), счётчик пилюли — 11 тестов
- [x] T014 `inspector_widget_test.dart`: пустые состояния, карточки/флаги/выделение, автоскролл, поля и чип, стиль-секция, sfx, факты, отчёт, кнопки — 3 теста
- [x] T015 `flutter analyze` clean + `flutter test` 103 passed (было 89)

## Converge

- [x] T016 Живой smoke (`tool/inspector_smoke.dart`, изолированный data dir, `test-img/test-1.jpg`): старт → импорт → перевод → документ (15 регионов) → текст (v2→3, `translation_locked`) → черновик стиля (2 правки, кегль 18, wave) → «Готово» → предпросмотр `ready` (PNG декодирован, offset) → стили проекта 3→4 → шрифты 156 (FontLoader без ошибок) → sfx-перестиль `ready` → сброс правок (v5→6, история очищена) → `SMOKE_DONE failures=0`, orphan-процессов нет
- [x] T017 Ручной проход окна — отложен: API-цикл и widget-тесты покрывают клики; канвас/окно проверяются в общем ручном прогоне 026

## Найдено в прогоне (исправлено)

- `ViewerState.dispose()` не отменял `_saveTimer` — «протекающий» таймер старого документа стрелял в тестах следующего сценария (найдено state-тестами, таймер отменяется в `dispose`)

## Отклонения от веба (зафиксировано)

- Пилюля «N правок» считает только неприменённые правки (023 считал всю историю): текстовые автосохранения в счёт не входят — иначе «не применены» врало бы.
- Вставка стиля (Ctrl+Shift+V) идёт в черновик до «Готово» (в вебе сохраняется сразу) — продолжение отклонения 023 «часть правок в вебе автосохраняется».
- Sfx-перекраска при активном черновике сначала применяет его; в вебе возможен вечный `whenSaved` при неприменённом черновике — здесь зависание исключено.
- Предпросмотр стиля отражает серверный (сохранённый) документ — как в вебе; отложенные правки до «Готово» серверу не видны.
- Отчёт — третья вкладка при `busy` или режиме «Прогон» (в мокапе — отдельный рельс); факты страницы остаются второй вкладкой.
- Шрифты каталога грузятся один раз при открытии рельса (151+ файлов через `FontLoader`); ошибки отдельных шрифтов не блокируют правку.
- «Загрузить свой шрифт…» и «Применить ко всем» из `style.html` не реализованы: в веб-клиенте и API нет соответствующего контракта (загрузка шрифта/применение к списку регионов).
