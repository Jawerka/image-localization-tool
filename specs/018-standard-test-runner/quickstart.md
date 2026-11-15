# Quickstart
См. docs/TEST_IMAGE_RUNNER.md: dry-run, run, status, gallery, resume и retry-errors.
Проверки: pytest tests/unit/test_test_images.py; node tests/js/test_review_gallery.mjs. Реальный smoke — один маленький исходник через существующий сервер, затем resume без отправки готового результата.

## Результат проверки 2026-11-14
20 Python-тестов прошли; Node проверил оба набора кнопок, сохранение оценок, JSON и fallback браузера. Реальный фоновый прогон 01--.png: 1/1 завершён, повторная команда не изменила PNG и оставила ровно одно событие page_started. Текущая галерея 53 страниц перестроена без распознавания. Полный повтор набора не выполнялся.
