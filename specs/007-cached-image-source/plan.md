# Implementation Plan: Чтение кэша исходника

**Branch**: `codex/007-cached-image-source` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

## Summary
Отдельный content-script image-source.js читает HTTP/blob/data в контексте страницы. HTTP fetch использует force-cache и таймаут 5 секунд на получение заголовков и тела; затем пробует origin-clean canvas загруженного IMG полного разрешения. Проверяется совпадение currentSrc с выбранным оригиналом до и после чтения. Защищённый canvas не обходится. Inline-script передаёт доступные байты через существующий imageBase64; если чтение недоступно, продолжает обычный запрос по URL.

## Technical Context
JavaScript MV3, Fetch/AbortController/Canvas; Python только для сборки и тестов. Новых зависимостей и хранилищ нет. Chromium и Firefox. Декодированные PNG могут отличаться кодированием от оригинала, но размер и видимые пиксели сохраняются. Размер Blob для сообщения <=32 МиБ; более крупные файлы идут через background, где остаётся лимит 64 МиБ.

## Constitution Check
I: пайплайн v2 не меняется. II: один helper и минимальная интеграция, нет настроек/движков. III: русские комментарии. IV: данные остаются локальными, кэш профиля не читается напрямую. V: метрики качества не затрагиваются. Новый файл helper добавляется в оба манифеста и список сборки. Проверка до и после проектирования: нарушений нет. Предыдущее изменение 006 сохранено локальным коммитом; PR/merge без разрешения не выполняются.

## Project Structure
- extension/src/image-source.js — самостоятельное получение и сериализация байтов страницы.
- extension/src/inline-content.js — вызов helper и существующее сообщение.
- extension/src/background.js — force-cache вместо no-store при загрузке, журнал HTTP/сетевых ошибок.
- extension/manifest.*.json, scripts/build-extension.py — доставка helper перед inline.
- tests/js/test_extension_image_source.mjs, tests/js/test_extension_background.mjs, tests/unit/test_extension_build.py — функциональные проверки.
- tests/e2e/test_extension_cached_source.py — реальный Chromium: прогрев кэша, выключенный источник, точные байты; защищённый canvas; полный размер пикселей.

## Validation
node:test, pytest сборки, локальный Playwright Chromium без доступа к пользовательскому профилю, сборка двух расширений. Повторная авторизация и расширение разрешений не нужны. После проверки — деплой распакованного расширения в ранее разрешённую папку, затем пользователь перезагружает расширение и вкладку (Chrome не подключён к управлению).
