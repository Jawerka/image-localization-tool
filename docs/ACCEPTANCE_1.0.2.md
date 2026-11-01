# Приёмка кандидата 1.0.2

Дата: 2026-11-01. Source commit `240c3e31990eb082c7567f7919a0da9304b344cf`. Машинный паспорт: [ACCEPTANCE_1.0.2.json](ACCEPTANCE_1.0.2.json).

Итог: **кандидат опубликован на этих байтах.** Обязательные ID приняты с оговорками ниже. CUDA (P06) отложена. Повторный Prepare из клона не запускался.

Digest `ghcr.io/jawerka/image-localization-tool@sha256:a4d874bd9bd072dfcb3306cc63401d2b496b5ebaf6d7fbb5237dd260cb1dd1c4`. Full ZIP SHA256 `19aaa1f1d919d15ed3fc643af4eb93db49ab31682f7b8d763847956874fdd894`.

## Что подтверждено

- CI PR #7: Python 3.10–3.13, Flutter, JS, browser E2E, updater fixture.
- Prepare: Windows light/full, Linux tar, Docker ZIP, GHCR `1.0.2-cpu-full`.
- OpenCV 4.13.0.92 (`opencv-python` и `opencv-python-headless`) в релизной базе, чистом клоне и Docker-образе.
- Windows full: Flutter smoke, перевод, ZIP-экспорт, `.ilt.zip` сохранить/закрыть/открыть.
- Windows light: подготовка в Prepare; отказ без манифеста понятен.
- Обновление 1.0.1 → 1.0.2 light staged, маркер в `data` сохранён.
- Docker Compose на LAN-хосте: смена 1.0.1 → 1.0.2, volume, restart, браузерный upload/translate/export.
- Расширение Chromium ZIP 1.0.2: сопряжение, health и перевод картинки через Docker `--headless --remote` того же digest (не через `--server` редактора).
- H03: отдельный clone тега `v1.0.2`, pip, неизменные каталоги, PyInstaller sidecar; Linux CI на том же теге собрал sidecar до отказа загрузить файлы в уже публичный релиз.
- LLM: VLM OCR и перевод «Hello world!» → «Привет, мир!».
- Маски: 20 пар и 6 sound-ref; пропуски (1)/(5) — OCR, не ретушь.

## Ограничения

Сложные японские и стилизованные SFX на sound-ref (1) и (5) по-прежнему пропускаются. T011 фичи 003 открыт. CUDA не заявлена. Q06 p95 — наблюдение на трёх прогонах, не устойчивая оценка. После публикации тег `v1.0.2` повторно запустил Release Linux; загрузка в публичный релиз была отклонена, файлы не менялись.
