# Tasks: Измерение времени и памяти

## Foundation
- [x] T001 Вернуть timings load/segment/inpaint/typeset в `PagePipeline.rerender`.
- [x] T002 Добавить измерение времени ожидания очереди в runtime-параметры воркера, не меняя формат persisted queue.
- [x] T003 Добавить latency header для preview.

## Evaluation
- [x] T004 Добавить повторы, labels cold/warm, I/O, file bytes и RSS sampling в `scripts/eval_pipeline.py`.
- [x] T005 Покрыть сериализацию отчёта и измерительные контракты unit-тестами.
- [x] T006 Выполнить повторный rerender на пяти исходных страницах и сверить quality metrics/pixel variation; отчёт `output/baseline-vlm-reference/eval-t23-rerender.json`.
