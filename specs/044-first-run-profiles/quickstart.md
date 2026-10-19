# Quickstart: Профили первого запуска

## Предпосылки

- Установлены зависимости проекта и Playwright браузер для UI проверки.
- Для API-проверки сетевые модели не требуются: ответы coordinator-а тестируются изолированно.

## Проверки

```powershell
venv\Scripts\python.exe -m pytest tests/unit/test_app_server.py::test_preparation_plan_endpoint_passes_profile_and_does_not_save_it tests/unit/test_app_server.py::test_unsupported_offline_preparation_does_not_change_settings tests/unit/test_preparation.py::test_unsupported_offline_pair_is_explicit -q
venv\Scripts\python.exe -m pytest tests/e2e/test_ui_smoke.py::test_first_run_shows_preparation_estimate_for_selected_profile -m ui -q
node --check web/js/settings.js
node --check web/js/api.js
```

Ожидается: API `3 passed`, целевой UI smoke проходит, обе JS проверки завершаются без ошибок. Для полного UI smoke набора см. `venv\\Scripts\\python.exe -m pytest -m ui tests/e2e/test_ui_smoke.py tests/e2e/test_extension.py -q`.

## Ручной первый запуск

1. Запустить приложение в чистом профиле настроек.
2. На шаге компонентов сверить список, байты загрузки и требуемое место до старта.
3. Запустить подготовку и проверить этапы загрузки/установки; при необходимости поставить на паузу и продолжить.
4. Завершить подготовку и выполнить первый перевод.
5. Повторить с offline профилем: существующая Argos пара должна появиться в плане; неизвестная должна показать причину и не менять настройки.

Ручная проверка реальной загрузки и перевода остаётся частью T18 и не считается доказанной тестом с подменённым API.
