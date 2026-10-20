# Spec Index

Обновлено: 2026-10-20. Это единственный реестр состояния спек. `tasks.md` хранит историю задач; текущий статус и приёмочный гейт определяются здесь. Доказательства текущей сборки и частичного маршрута — в [ACCEPTANCE_1.0.5.md](../docs/ACCEPTANCE_1.0.5.md).

## Статусы

- `accepted` — реализовано и принято на целевой поверхности.
- `implemented` — код и задачи закрыты; приёмка на Flutter EXE ещё не записана.
- `blocked-acceptance` — реализация есть, не хватает внешней или платформенной приёмки.
- `in-progress` — есть незакрытые задачи реализации.
- `superseded` — заменено более поздней спекой или релизом.
- `deferred` — сознательно отложено и не блокирует 1.0.5.

## Что блокирует 1.0.5

| Spec | Гейт |
|---|---|
| 030 | `T024`: приёмка cu128 на Windows (cu130 уже принят в 033; оба профиля остаются в runtime). |
| 032 | `T025`: installer smoke. `T027` (v1.0.1) исторический и заменён 1.0.2/1.0.5. |
| 036 | Реальная приёмка Flutter EXE; Flutter parity инспектора реализован, web закрыт (10/10). |
| 037 | Firefox и живой Reddit; синтетический Chromium закрыт (4/4). |
| 038 | Реальная приёмка Flutter EXE; `text_position` и жест перемещения реализованы, web/backend закрыты (7/7). |
| 039 | `T001` WebView2/GPU memory и визуальная приёмка; Flutter draft mesh preview реализован, web закрыт (7/8). |
| 044 | `T011` чистая подготовка + реальная приёмка Flutter EXE; профили local/server/offline реализованы (12/13). |
| 045 | `T010` чистый Linux/systemd и CT113; реализация и fake-root сценарии закрыты (9/10). |
| 048 | `T004`/`T005`; Flutter-вкладки реализованы, web закрыт (3/5). |

`023 T016` переведён в `deferred` (jank-профиль, не блокер). `031 T020` заменён решением по CUDA в 030/033. `001` — исторический baseline-аудит, не текущий долг.

## Реестр

| Spec | Surface | State | Evidence | Open gate / note |
|---|---|---|---|---|
| 001-baseline-contract | all | superseded | [tasks](001-baseline-contract/tasks.md) 3/32, historical | 29 проверок оставлены для провенанса; контракт закрыт через 002/003/033 |
| 002-fix-contract-gaps | backend + web | implemented | [tasks](002-fix-contract-gaps/tasks.md) 15/15 | — |
| 003-page-editor-typeset | web + backend | implemented | [tasks](003-page-editor-typeset/tasks.md) 20/20 | — |
| 004-style-card-polish | web | implemented | [tasks](004-style-card-polish/tasks.md) 11/11 | — |
| 005-editor-harden-e2e | web | implemented | [tasks](005-editor-harden-e2e/tasks.md) 7/7 | — |
| 006-deploy-ci | deploy | implemented | [tasks](006-deploy-ci/tasks.md) 6/6 | — |
| 007-fallback-warnings | backend + web | implemented | [tasks](007-fallback-warnings/tasks.md) 6/6 | — |
| 008-frontend-unit-ci | web + CI | implemented | [tasks](008-frontend-unit-ci/tasks.md) 6/6 | — |
| 009-deploy-extension-inno | deploy | implemented | [tasks](009-deploy-extension-inno/tasks.md) 4/4 | — |
| 010-lama-ring-tighten | backend | implemented | [tasks](010-lama-ring-tighten/tasks.md) 4/4 | — |
| 011-soft-mask-edges | backend | implemented | [tasks](011-soft-mask-edges/tasks.md) 4/4 | — |
| 012-portable-project | web + backend | implemented | [tasks](012-portable-project/tasks.md) 19/19 | — |
| 013-bubble-contour-mask | web + backend | implemented | [tasks](013-bubble-contour-mask/tasks.md) 10/10 | — |
| 014-deferred-style-undo | web | implemented | [tasks](014-deferred-style-undo/tasks.md) 8/8 | — |
| 015-editor-session-tools | web | implemented | [tasks](015-editor-session-tools/tasks.md) 7/7 | — |
| 016-floating-done | web | implemented | [tasks](016-floating-done/tasks.md) 5/5 | — |
| 017-inspector-manual-stroke | web | implemented | [tasks](017-inspector-manual-stroke/tasks.md) 5/5 | — |
| 018-free-ocr-edit | web + backend | implemented | [tasks](018-free-ocr-edit/tasks.md) 4/4 | — |
| 019-manual-translation-paint | web + backend | implemented | [tasks](019-manual-translation-paint/tasks.md) 4/4 | — |
| 020-editor-shell-polish | web | implemented | [tasks](020-editor-shell-polish/tasks.md) 10/10 | — |
| 021-flutter-shell-host | Flutter | implemented | [tasks](021-flutter-shell-host/tasks.md) 20/20 | — |
| 022-main-window-states | Flutter | implemented | [tasks](022-main-window-states/tasks.md) 15/15 | — |
| 023-viewer | Flutter | implemented | [tasks](023-viewer/tasks.md) 15/16 | `T016` deferred: jank-профиль не блокирует 1.0.5 |
| 024-inspector | Flutter | implemented | [tasks](024-inspector/tasks.md) 17/17 | — |
| 025-secondary-screens | Flutter | implemented | [tasks](025-secondary-screens/tasks.md) 18/18 | — |
| 026-cutover | Flutter + deploy | implemented | [tasks](026-cutover/tasks.md) 20/20 | — |
| 027-viewer-fixes | Flutter | implemented | [tasks](027-viewer-fixes/tasks.md) 14/14 | — |
| 028-editor-ux | Flutter | implemented | [tasks](028-editor-ux/tasks.md) 18/18 | — |
| 029-page-switch-home | Flutter | implemented | [tasks](029-page-switch-home/tasks.md) 7/7 | — |
| 030-runtime-deployment | backend + deploy | blocked-acceptance | [tasks](030-runtime-deployment/tasks.md) 25/26 | `T024` cu128; cu130 принят в 033 |
| 031-release-packaging | deploy | superseded | [tasks](031-release-packaging/tasks.md) 21/22 | `T020` перенесён в 030/033; упаковка 1.0.0/1.0.2 выпущена |
| 032-runtime-wheelset | deploy | blocked-acceptance | [tasks](032-runtime-wheelset/tasks.md) 31/33 | `T025` installer smoke; `T027` исторический |
| 033-reliable-component-delivery | backend + deploy | accepted | [tasks](033-reliable-component-delivery/tasks.md) 28/28 | Windows/CUDA/Linux приёмка записана |
| 034-readable-balloon-layout | backend | implemented | [tasks](034-readable-balloon-layout/tasks.md) 8/8; [results](../docs/BALLOON_LAYOUT_RESULTS.md) | — |
| 035-rectangular-text-layout | backend | implemented | [tasks](035-rectangular-text-layout/tasks.md) 9/9; [results](../docs/RECTANGULAR_LAYOUT_RESULTS.md) | — |
| 036-inspector-redesign | web → Flutter | blocked-acceptance | [tasks](036-inspector-redesign/tasks.md) 10/10; Flutter parity реализован | Реальная приёмка Flutter EXE |
| 037-extension-overlay | extension | blocked-acceptance | [tasks](037-extension-overlay/tasks.md) 4/4; [research](037-extension-overlay/plan.md) | Firefox и живой Reddit |
| 038-text-placement | web + backend → Flutter | blocked-acceptance | [tasks](038-text-placement/tasks.md) 7/7; Flutter `text_position` реализован | Реальная приёмка Flutter EXE |
| 039-local-mesh-preview | web → Flutter | blocked-acceptance | [tasks](039-local-mesh-preview/tasks.md) 7/8; Flutter draft mesh preview реализован | `T001` WebView2/GPU memory + визуальная приёмка |
| 040-bounded-prefetch | backend | implemented | [tasks](040-bounded-prefetch/tasks.md) 7/7 | — |
| 041-performance-instrumentation | backend | implemented | [tasks](041-performance-instrumentation/tasks.md) 6/6; [research](041-performance-instrumentation/research.md) | — |
| 042-bounded-render-cache | backend | implemented | [tasks](042-bounded-render-cache/tasks.md) 7/7 | — |
| 043-preview-compose | backend | implemented | [tasks](043-preview-compose/tasks.md) 3/3; [research](043-preview-compose/research.md) | — |
| 044-first-run-profiles | web → Flutter | blocked-acceptance | [tasks](044-first-run-profiles/tasks.md) 12/13; профили local/server/offline в Flutter | `T011` чистая подготовка + реальная приёмка Flutter EXE |
| 045-linux-service-deployment | deploy | blocked-acceptance | [tasks](045-linux-service-deployment/tasks.md) 9/10; [research](045-linux-service-deployment/research.md) | `T010` Linux/systemd/CT113 |
| 046-windows-staged-update | deploy | implemented | [tasks](046-windows-staged-update/tasks.md) 11/11; [research](046-windows-staged-update/research.md) | Linux/installer GUI остаются в 032/045 |
| 047-incremental-typeset-composition | backend | implemented | [tasks](047-incremental-typeset-composition/tasks.md) 20/20; [research](047-incremental-typeset-composition/research.md) | — |
| 048-sidebar-tabs | web → Flutter | in-progress | [tasks](048-sidebar-tabs/tasks.md) 3/5; Flutter-вкладки реализованы | `T004`/`T005` |
| 049-viewer-layer-prefs | Flutter + backend | in-progress | [tasks](049-viewer-layer-prefs/tasks.md) 10/11; analyze, 142 Flutter-теста, pytest | `T009`: ручная проверка после перезапуска |

## Правило приёмки

`accepted` ставится только после реального прогона на целевой поверхности: Flutter EXE, расширение в Firefox/Chromium или чистый Linux-хост. Зелёные unit/UI-тесты с FakeWorker или синтетическим Chromium сами по себе не переводят спеку в `accepted`.
