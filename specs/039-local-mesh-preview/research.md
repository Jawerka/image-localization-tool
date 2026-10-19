# Исследование renderer (T14)

Дата: 2026-10-18.

## Эксперимент

- Browser: Playwright Chromium, `HeadlessChrome/153.0.8010.12`, Windows 10 x64.
- PixiJS: 8.21.0, `MeshPlane`; сравнение с отдельным минимальным WebGL renderer.
- Одна и та же текстура: RGBA 800×400, русская строка «Привет, мир! Ёжик 123», белая заливка и тёмная обводка.
- Mesh: 16×12 ячеек, каждая поделена на 4×4 участка; 3 185 вершин / 6 144 треугольника.
- Выполнено по 180 `requestAnimationFrame` итераций на renderer; первые 15 отброшены как прогрев. В метрике `updateAndSubmit` замеряются обновление CPU-массива, загрузка вершин и отправка draw call, без синхронного ожидания GPU.
- JS heap после инициализации обоих renderer: около 10 MB used / 14,3 MB total (`performance.memory`). Это общий heap страницы, не GPU memory и не отдельный расход PixiJS.

| Renderer | p50, ms | p95, ms | max, ms |
|---|---:|---:|---:|
| Минимальный WebGL | 0,2 | 0,4 | 0,4 |
| PixiJS MeshPlane | 0,3 | 0,4 | 0,5 |

## Решение

Выбран минимальный WebGL renderer: PixiJS не показал выигрыша в данном сценарии, а runtime-проект избегает дополнительной зависимости и её bundle. Оба renderer теперь используют `preserveDrawingBuffer`, как подключённый overlay. Это CPU submission time, а не полная стоимость GPU кадра. Результат preliminary: headless Chromium — не WebView2; число замеров ограничено, GPU memory не измерялась. WebView2 недоступен, поэтому T14 остаётся открытой до проверки согласованного WebView2. Для подключённого viewer целевой drag-сценарий прошёл в Chromium; это не заменяет замер на WebView2.

## Интеграционный прогон T15

- Встроенный RGBA base-layer сохраняется на протяжении жеста; пиксельная проверка canvas видит одновременно непрозрачные чернила и прозрачные пиксели.
- Chromium UI-сценарий: выбор mesh v2 → локальный preview во время drag → один шаг сохранения → undo/redo; invalid cell не коммитится.
- Повторный benchmark с `preserveDrawingBuffer` показал p95 CPU submission 0,4 ms для обоих renderer; медиана/p95 интервала RAF — около 16,9/18,0 ms. Это предварительный результат headless Chromium, не WebView2 acceptance run.
- T15 функционально готова в Chromium. Требование проверки в WebView2 и сравнения с точным экспортом на реальных страницах остаётся внешним gate.

## Повторная проверка WebView2

- Установленное desktop-приложение v1.0.2 запущено без открытия пользовательского проекта; встроенный UI перешёл из «Запуск…» в «Готово».
- Accessibility bridge прочитал дерево UI, но screenshot capture и следующий input bridge завершились timeout/недоступной геометрией окна. Renderer p95 и GPU memory измерить не удалось; Chromium цифры не засчитываются как WebView2 acceptance.
- Затем запущен изолированный WebView2 harness с настоящим `MeshPreviewRenderer` и синтетической RGBA-страницей 800×400. Окно renderer-процесса создалось, но локальный benchmark callback/JSON не пришёл; процесс и временный WebView2-профиль закрыты и удалены. Это не считается измерением: WebView2 p95 и GPU memory остаются незакрытым gate.
- Дополнительно запущен packaged Flutter host с `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=49387`; localhost `/json/version` не появился за 45 секунд, поэтому CDP-замер тоже недоступен. Host остановлен, временная распаковка удалена.

## Повторные функциональные проверки

- Chromium UI test `test_mesh_context_loss_restores_exact_preview`: через `WEBGL_lose_context` теряется активный контекст во время mesh drag; draft canvas скрывается, точный серверный PNG становится видимым, пользователь видит fallback-сообщение. Тест прошёл.
- API/Typesetter test `test_mesh_exact_preview_matches_full_export_render`: mesh v2 с rotation рендерится exact-preview endpoint и полным экспортным `Typesetter.render`; декодированный preview crop совпал с полноразмерным результатом пиксель-в-пиксель. Тест прошёл.
- Chromium UI test `test_mesh_drag_cancels_on_escape_and_pointercancel` подтвердил восстановление узла после отмены обоими жестами. Существующий UI mesh-сценарий покрывает один undo/redo для одиночного узла и группового drag, zoom, invalid-cell отказ, геометрию сетки, ширину инспектора 344 px и обе темы.
- После переноса ожидания загрузки RGBA-слоя перед проверкой клавиатурного Tab-порядка UI smoke проходит полностью: `14 passed`. Полный Python suite по текущему дереву: `607 passed, 1 skipped`.

Источник API для MeshPlane: [PixiJS v8.21 MeshPlane](https://pixijs.download/v8.21.0/docs/scene.MeshPlane.html).
