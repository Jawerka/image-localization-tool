# Linux LAN-сервер

Linux release asset содержит замороженное приложение и не требует developer venv. Для управляемой установки с systemd используйте отдельные bootstrap и update-команды. Данные, модели, OCR-компоненты и runtime-паки хранятся отдельно от версий приложения.

## Первичная установка

1. Скачайте официальный Linux server archive и проверьте его SHA-256 из release assets.
2. Распакуйте архив в отдельный каталог.
3. Запустите от администратора:

   ```sh
   sudo ./install-server-linux.sh --bundle ./ImageLocalizationTool --root /opt/image-localization-tool
   ```

   При первом запуске команда создаёт системного пользователя `ilt`, shared-каталоги, устанавливает компоненты (`--deploy all`), регистрирует `ilt.service` и ждёт готовности API.

4. Проверьте службу и health API:

   ```sh
   sudo systemctl status ilt.service
   curl --fail http://127.0.0.1:8765/v1/health
   ```

Повторный запуск с той же версией проверяет службу и не копирует компоненты заново. Для другой версии используйте updater. Если сервер уже использует внешний LLM и не нужен локальный fallback, первичную установку можно выполнить с `--skip-components`.

## Обновление

Распакуйте новый официальный архив во временный каталог и запустите:

```sh
sudo ./update-server-linux.sh --bundle ./ImageLocalizationTool --root /opt/image-localization-tool
```

Updater размещает кандидата в `releases/<version>`, переключает `current` и проверяет `/v1/health`. Он не загружает и не заменяет модели или runtime-паки. При ошибке запуска или readiness возвращает прежний `current` и проверяет восстановленную службу.

## Откат

```sh
sudo ./rollback-server-linux.sh --root /opt/image-localization-tool
```

Команда переключает `current` на сохранённый `previous`, проверяет API и сохраняет обе версии. Каталоги `shared/data`, `shared/models`, `shared/runtime` и `shared/.resources` не удаляются.

Операции установки, обновления и отката используют один lock. Health timeout по умолчанию — 60 секунд; его можно изменить через `--health-timeout`. Корень по умолчанию `/opt/image-localization-tool`.

Для запуска приложения в foreground без systemd по-прежнему доступен `./deploy.sh`.

## Проверки перед использованием на CT113

Release workflow выполняет fake-root тесты успешной установки, повторной установки, успешного обновления, forced health rollback, явного отката, сохранности shared-файла и блокировки параллельной операции. Это не заменяет чистую Linux/systemd установку и перевод реальной страницы; эти проверки выполняются перед публикацией на выделенном Linux-хосте.
