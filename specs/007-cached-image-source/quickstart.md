# Проверка

```powershell
node --test tests/js/test_extension_image_source.mjs tests/js/test_extension_background.mjs
venv/Scripts/python.exe -m pytest tests/unit/test_extension_build.py tests/e2e/test_extension_cached_source.py -q
venv/Scripts/python.exe scripts/build-extension.py
```

Требуются requirements-dev и установленный Playwright Chromium. Браузерный тест использует локальный временный профиль. Источник картинки после прогрева выключается; чтение из кэша должно сохранить точные байты без нового запроса. Защищённый canvas даёт пустой результат, читаемый — PNG исходного размера. Проверка конкретного H@H-сервера и реальный перевод выполняются отдельно, без заявления accepted по одним тестам.
