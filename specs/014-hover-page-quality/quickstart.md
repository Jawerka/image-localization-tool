# Validation
1. Выполнить pytest tests/e2e/test_extension_safe.py.
2. Выполнить node --test tests/js/test_extension*.mjs.
3. Полностью обработать два исходных JPG с настройками приложения, сохранить debug и результат в output/hover-page-quality.
4. Сопоставить маски только после обработки, визуально проверить оригинал/очистку/результат.
5. Повторить выборочные старые страницы; записать результаты и ограничения в docs/BENCHMARK_RESULTS.md.
