# Implementation Plan: Стандартный прогон
**Branch**: codex/018-standard-test-runner | **Date**: 2026-11-14 | **Spec**: spec.md
## Summary
CLI scripts/test_images.py управляет последовательными отдельными процессами PagePipeline; scripts/templates/review_gallery.html — общий шаблон. Существующий отчёт поддерживается командой gallery без OCR.
## Technical Context
Python 3.10–3.13, stdlib, текущий Config/PagePipeline/Pillow. JSON и HTML только в output. pytest и Node для проверки очереди и экспорта. Windows/Linux. Один процесс страницы; тайм-аут, атомарные отчёты и блокировка каталога.
## Constitution Check
Пайплайн v2, минимальный diff, русские комментарии, локальные артефакты и отсутствие секретов соблюдены. Качество не объявляется гарантированным. PR/деплой не входят в запрос. Проверено до и после проектирования.
## Project Structure
scripts/test_images.py; scripts/templates/review_gallery.html; tests/unit/test_test_images.py; tests/js/test_review_gallery.mjs; docs/TEST_IMAGE_RUNNER.md.
## Decisions
Сохранять снимок эффективного Config без API-ключа и исходный набор с хешами. Проверять неизменность src, сценария, шаблона и конфигурации при resume. Рендер галереи разрешён для старого report.json. Блокировка снимается ОС после аварии. Код завершения 0 — всё готово, 1 — ошибки страниц, 2 — ошибка запуска, 130 — прерывание. Время ожидания ведёт сам процесс, агент не опрашивает страницы.

Уточнение: --images и --list-file (TXT/JSON) задают точный список локальных файлов, включая внешние каталоги. В manifest сохраняется source_path. Родитель читает маркеры прогресса из process.log без потоков и выводит стадии/ожидание в консоль. Фоновому процессу передаётся сохранённый список абсолютных путей, без ограничения длиной команды.
