# Implementation Plan: Надёжная докачка компонентов

**Branch**: `033-reliable-component-delivery` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)
**Input**: docs/DOWNLOAD_DELIVERY_PLAN.md.

## Summary

Сохранить sidecar, Flutter и v2. Добавить общий загрузчик, фиксированный каталог, журнал подготовки, проверку до переключения, общий экран подготовки и релизный оркестратор.

## Technical Context

**Language/Version**: Python 3.10–3.13 (релиз ABI 310), Dart/Flutter, PowerShell 5.1.
**Primary Dependencies**: stdlib urllib/hashlib/zipfile, существующие PyInstaller, ONNX Runtime, RapidOCR, Argos, PyTorch.
**Storage**: атомарные JSON-журналы, кэш SHA256, каталоги ревизий и активные указатели.
**Testing**: pytest с локальным HTTP-сервером, Flutter analyze/test, frozen Windows/Linux smoke.
**Target Platform**: Windows desktop/portable и Linux server.
**Performance Goals**: память загрузки ограничена чанком, подтверждённые файлы не скачиваются повторно.
**Constraints**: нет сетевых операций внутри перевода/OCR; публикация после ручной приёмки.
**Scale/Scope**: runtime, модели/OCR/языки/шрифты, мастер, скрипты выпуска.

## Constitution Check

Пайплайн v2 и прежние CLI/HTTP/LAN входы сохраняются. Инфраструктура выделена в src/app; новые настройки в Config с дефолтами; русские комментарии. Модели/данные/ключи не коммитятся. Benchmark не переинтерпретируется. Проверка до и после проектирования пройдена.

## Project Structure

Документы: spec, plan, research, data-model, contracts/preparation-api, quickstart, tasks.
Код: src/app/{downloads,component_catalog,component_check,preparation}.py; runtime/model_manager/server/deploy/hardware; utils/paths; config; components/rapid_ocr и translator.
Flutter: state/secondary_state, shell_state; общий preparation_panel; first_run/settings.
Сборка: locks/runtime-catalog.json, assets/argos wheel, scripts/release.ps1 и release workflow.

## Phases

1. Зафиксировать каталог runtime обеих платформ и ресурсов; release читает его без resolve. Встроенные данные авторитетны, env override валидируется.
2. Общий SHA256-кэш: Range/If-Range, размер/хэш, retry/mirrors, пауза между чанками. OS-lock Windows msvcrt/Linux flock освобождается при падении.
3. Новые установки runtime в .revisions/id/revision; атомарный .active/id.json. Legacy каталоги читаются. Проверка отдельным frozen-процессом до переключения, inventory в маркере. Выбирается один torch. Parent sidecar не импортирует torch для статуса; новый worker использует активный указатель.
4. Persistent preparation.Manager сериализует весь набор; SSE + GET snapshot; пауза/возобновление, план с замороженными ревизиями.
5. Components-root: normal → data_root/components, portable/server → install-root; legacy читается без скрытой миграции. RapidOCR получает внешние пути. Argos язык устанавливается до обработки.
6. Мастер выбирает режим/языки до загрузки, общий объём и одна кнопка; настройки предоставляют тот же panel; reconnect перечитывает snapshot.
7. release.ps1 Prepare генерирует одинаковые каталоги до сборок, собирает и сохраняет отчёт/хэши; Publish не пересобирает, проверяет анонимные источники и неизменность candidate.

## Validation

Локальные HTTP-сбои, повреждённый кэш, транзакционные установки, межпроцессная блокировка, SSE reconnect, CPU/GPU рекомендации. Затем полный pytest/Flutter, аудит упаковки и реальные frozen CPU/Argos/OCR, Linux и CUDA smoke. Недоступность внешнего источника/сборки фиксируется как ограничение, не как успех.

## Complexity Tracking

Новые модули разделяют каталог, загрузку и очередь. Старые schema 1/2 читаются адаптером. Независимый хостинг не создаётся.
