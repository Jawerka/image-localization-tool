# Tasks: Экономная композиция preview

## Foundation
- [x] T001 Выделить общий проход layout/overlay в `src/components/typesetter.py`; публичный `render()` сохраняет полную композицию, `render_layer()` пропускает её.

## User Story 1 — Локальный crop preview (P1)
- [x] T002 Композировать слой на ограниченном crop в `src/app/server.py`, сохранив origin, bounds и clipping.
- [x] T003 Подтвердить pixel identity в `tests/unit/test_app_server.py` и `tests/unit/test_typesetter.py`; A/B 2500×3500, 3 процесса: медиана времени 381.7→349.3 ms, RSS delta 219.8→153.3 MiB.
