# Implementation Plan: Ограниченная предварительная загрузка

**Branch**: `codex/036-inspector-redesign` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary

Перед последовательной установкой компонентов подготовить уникальные отсутствующие файлы параллельной очередью с ограниченным worker count. Повторно использовать `downloads.fetch`, чтобы сохранить контроль размера, SHA-256, Range/If-Range, pause/resume и кэш.

## Technical Context

- **Language/Version**: Python 3.10–3.13.
- **Primary Dependencies**: stdlib `concurrent.futures`; существующие `downloads`, `runtime`, `component_catalog`.
- **Storage**: существующий content-addressed download cache и persisted `preparation.json`.
- **Testing**: pytest с локальным HTTP fixture, без внешней сети.
- **Target Platform**: Windows и Linux; одинаковая реализация Python.
- **Performance Goals**: при worker limit >1 допускается одновременная загрузка независимых файлов; число активных запросов строго ограничено настройкой.
- **Constraints**: верхняя граница 4; существующие locks и integrity checks сохраняются; установка и активация последовательны.
- **Scale/Scope**: только очередь подготовки ресурсов/моделей/runtime.

## Constitution Check

- Pipeline v2 не изменяется.
- Используется существующий download manager; новый загрузчик не создаётся.
- Новая настройка `Config.download_prefetch_workers` получает значение по умолчанию.
- Частичный кэш остаётся вне Git.
- Никакие секреты не сериализуются.

## Research Decisions

- Переиспользовать `downloads.fetch` на каждый уникальный `Artifact`, а не распараллеливать методы `install`: это сохраняет текущую транзакционную установку.
- Предварительно скачать все файлы выбранного плана до начала установки. Ошибка не активирует частично подготовленный набор.
- Уникальность определяется SHA-256; если для одинакового хэша описаны несовпадающие размеры, остановить подготовку как ошибку каталога.
- Worker count читается из Config, нормализуется в диапазон 1–4 и по умолчанию равен 3.

## Project Structure

```text
src/config.py
src/app/preparation.py
tests/unit/test_preparation.py
tests/unit/test_downloads.py
```

## Verification

- локальный HTTP сервер измеряет максимум параллельных ответов;
- тестирует worker limit 1 и 3, dedup по SHA, паузу, обрыв и checksum;
- проверяет, что методы install не вызываются, пока все prefetch futures не завершились успешно;
- запускает `pytest tests/unit/test_downloads.py tests/unit/test_preparation.py`.
