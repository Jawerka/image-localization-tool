# Implementation Plan: FastStone quick translate
**Branch**: `codex/016-faststone-quick-translate` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Summary
ПК принимает файлы из FastStone в отдельное Flutter-окно и последовательно отправляет их на http://192.168.88.41:8765. Протокол идентичен extension/src/background.js: health → multipart translate → poll → PNG → DELETE. Локального перевода и локального фолбэка нет. Редактор и quick используют один локальный сайдкар; ProcessWorker ленивый и не получает quick-заданий.

## Technical Context
Python 3.10–3.13, Dart/Flutter, C++ Windows runner. Pillow для просмотра и сохранения, urllib для LAN-клиента, существующие file_selector/Win32/MethodChannel. Новая настройка quick_server_url в Config/AppSettings с дефолтом подтверждённого IP. Bearer отдельно в data/quick-server-token.txt. Результаты в data/quick/projects, отчёты data/bug-reports. Тесты pytest, настоящий RemoteServer без моделей, Flutter tests/analyze, Windows build. Таймаут HTTP 60 секунд, задачи с очередью 2 часа; опрос 600 мс; одно отправляемое quick-задание одновременно.

## Constitution Check
До и после дизайна: v2 вызывается серверным worker, не дублируется на ПК; минимальная интеграция отдельными модулями; русские комментарии; данные только data/; секреты не попадают в репозиторий и отчёты. Контракт расширения по умолчанию неизменен; diagnostics=1 — необязательное дополнение. Удаление активной серверной задачи теперь передаёт отмену её worker-заданию. Отдельная ветка; существующие изменения 015 сохранены. Деплой/PR/слияние отдельно от реализации.

## Project Structure
- src/app/quick.py — локальная очередь HTTP-клиента, файлы, отчёты, серверное сопряжение.
- src/app/quick_remote.py — протокол расширения, лимит multipart, Bearer, poll, cleanup/cancel.
- src/app/server.py, web_server.py — локальные quick-маршруты; запрет LAN/browser доступа к файловым путям ПК.
- src/app/remote.py, desktop.py — серверная отмена worker и необязательная диагностика задания без секретов.
- src/config.py, src/app/settings.py — quick_server_url.
- apps/desktop/lib/src/quick/ — отдельный виджет, состояние, native channel.
- apps/desktop/lib/main.dart, src/sidecar/single_instance.dart — IPC mode и coordinator; child engine запускает только API-клиент.
- apps/desktop/windows/runner/ — второе окно одного процесса, show/hide/close, UTF-8 заголовки.
- tests/unit/test_quick.py, apps/desktop/test/quick_test.dart, single_instance_test.dart — проверки.
- docs/APP.md — FastStone, сервер и сопряжение.

## Validation
Доказать отсутствие вызовов локального worker. Настоящий HTTP-контракт RemoteServer: pair/upload/poll/result/delete, лимиты, отмена, ошибка среднего файла, дедупликация, legacy без diagnostics. Проверить сохранение, секреты и изоляцию редактора. Проверить Flutter и Windows build. Live health подтверждённого IP отдельно от авторизованного прогона. Ручная цепочка FastStone отмечается только после фактической проверки. Установленный сервер не обновляется в рамках сборки.
