# Progress: 003-page-editor-typeset

**Updated**: 2026-10-09 (QA + hygiene)

## Сделано

### Первый–третий прогон
US1–US9 / FR-001–016 / T001–T020: результат при вёрстке, «Готово», синий след, прямая первая раскладка, pivot, inset/short-reply, arc/mesh, стиль на карточке, layout_long_side=2000; вкладка «Стиль» удалена.

### QA (2026-10-09)
Автопроверка по чеклисту (unit + маркеры UI):

| Проверка | Результат |
|----------|-----------|
| Готово / deferApply | OK (`state.js`, `viewer.js`, кнопка в `index.html`) |
| Синий след | OK `#2563eb` opacity 0.55 |
| Результат не мигает | OK `showResultGap` |
| Дуга вверх (середина выше краёв) | OK unit `test_arc_raises_midline_not_sideways` |
| Mesh init + bbox→layer | OK unit + `defaultMeshPoints` в inspector |
| Pivot / field center | OK unit `test_field_center_and_bbox_mesh_mapping` |
| Мелкая страница → 2000 | OK unit `test_layout_scale_lifts_small_page_to_2000` |
| Short-reply cap | OK unit |
| Стиль на карточке, без вкладки | OK |
| SFX без угла | OK `test_merge_sfx_keeps_straight_layout` |
| pytest typesetter/warp/sfx | 32 passed |

Визуальная ручка поворота / перетаскивание mesh глазами в окне — не гонялись; код и unit закрывают контракт.

### Hygiene
Закрытые пункты убраны из `docs/PROBLEMS.md`. Остались Flutter (отложено) и три хвоста UX (пресеты проекта, font-face в select, wave≠flag).

## Converge
Чистый: FR/T001–T020 удовлетворены; `tasks.md` без Phase Convergence.

## Файлы
- `src/components/typesetter.py`, `text_warp.py`, `page_pipeline.py`, `config.py`, `app/settings.py`
- `web/js/inspector.js`, `viewer.js`, `state.js`, `main.js`, `web/index.html`
- `tests/unit/test_typesetter.py`, `test_text_warp.py`
- `docs/PROBLEMS.md`
