# Результаты проверки — 2026-11-03

- Python: tests/unit/test_app_remote.py и tests/unit/test_extension_build.py — 26 passed.
- JavaScript: tests/js/test_extension_background.mjs — 15 passed.
- scripts/build-extension.py — успешно; dist/chromium, dist/firefox и ZIP собраны.
- git diff --check — без замечаний.
- Настоящая HTTP-передача тестового корректного PNG 29 865 297 байт локальному RemoteServer: 202, задание done, исходные байты сохранены. Модели не запускались.
- Проверены точный размер multipart, включительная граница, превышение на байт, старый/некорректный health, отказ до POST, HTTP 413 с JSON и без него, сохранение кода задания, различение сетевого и локального TypeError.
- Исходная пользовательская картинка: заголовок PNG 3387×4815, Content-Length 29 865 297. В LAN app.log за 17:37:12 — POST 413, соседние health 200.
- По запросу пользователя выполнен деплой в Windows portable, LAN /opt/image-localization-tool и распакованное Chromium-расширение. Установленный Windows-сайдкар запущен с отдельными диагностическими данными внутри data/tmp и проверен через health: ready=true, max_body_bytes=67108864; диагностический процесс завершён. LAN health подтверждает те же значения. Полный перевод исходной страницы после обновления пока не проверен; статус accepted не присвоен.
- PR и слияние не выполнялись. Деплой разрешён пользователем сообщением «Сделай деплой во все места». Ветка codex/006-large-image-upload.

## Проверки деплоя

- Windows: scripts/build-windows.ps1 -SkipFlutter -SkipModels, scripts/deploy-windows.ps1, smoke_dist --expect-no-torch — успешно. Данные, модели и runtime сохранены штатными исключениями скрипта. SHA256 установленного сайдкара совпадает с новой сборкой.
- Расширение: scripts/deploy-extension.ps1 — успешно, SHA256 background.js совпадает с исходником. Доступного Chrome в браузерном управлении нет: для активации пользователь должен перезагрузить расширение и вкладку.
- LAN: scripts/deploy-lan.ps1 -ProxyJump '' — успешно, служба active. Исправлена найденная ошибка проверки ready: пробелы в JSON больше не дают ложный отказ. tests/unit/test_deploy_scripts.py — 8 passed; после исправления полный скрипт выполнен успешно.
