# Tasks
## Phase 1: Baseline
- [x] T001 Сохранить полный прогон пяти страниц в output/extended-cases.
## Phase 2: US1 — Документы
- [x] T002 [US1] Добавить признак document и тесты совместимости в src/models.py и tests/unit/test_document_layout.py.
- [x] T003 [US1] Реализовать определение документа и безопасные текстовые границы в src/components/document_layout.py и text_regions.py.
- [x] T004 [US1] Сохранить семантику и обычную типографику в vlm_ocr.py, font_catalog.py, text_segmenter.py и typesetter.py.
- [x] T005 [US1] Сравнить методы прямоугольной раскладки, сохранить output/extended-cases/document-study.
## Phase 3: US2 — Новые страницы
- [x] T006 [US2] Проверить результаты комиксов и устранить подтверждённые утечки маски в src/components/bubble_contour.py с регрессионными тестами.
- [x] T007 [US2] Проверить сохранность трёх принятых масок и перерендерить новые страницы через PagePipeline.
## Phase 4: Validation
- [x] T008 Пройти тесты, осмотреть результаты и записать docs/RECTANGULAR_LAYOUT_RESULTS.md.
- [x] T009 Выполнить speckit-converge.

Dependencies: baseline → US1/US2 → Validation. Выполнение последовательно; независимы проверки разных страниц. MVP: исправить основной абзац скриншота, затем UI-подписи и регрессии комиксов.
