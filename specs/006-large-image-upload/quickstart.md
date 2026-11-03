# Проверка

Из корня с установленными requirements-dev:

```powershell
venv/Scripts/python.exe -m pytest tests/unit/test_app_remote.py tests/unit/test_extension_build.py -q
node --test tests/js/test_extension_background.mjs
venv/Scripts/python.exe scripts/build-extension.py
```

Ожидается: PNG больше 20 МиБ принят без изменения байтов; health сообщает 64 МиБ; старый сервер блокирует большую передачу до POST; 413 и локальный TypeError не называются отсутствующим сервером. Проверить приложение с обновлённым сервером и перезагруженным расширением отдельно перед статусом accepted. Здесь реальный перевод не заявлен.
