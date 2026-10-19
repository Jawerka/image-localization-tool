# Implementation Plan: Независимое размещение текста

**Branch**: `codex/036-inspector-redesign` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary
Добавить совместимую модель позиции текста, извлечь прозрачный текстовый слой из Typesetter, вернуть его в preview с координатами и подключить холстовый drag с одной исторической записью.

## Technical Context
- Python/Pillow renderer и существующий JSON-документ проекта.
- Новое поле необязательное; старый документ трактуется как identity.
- `text_position` хранит абсолютный центр текстового поля в координатах страницы; для отсутствующего значения применяется старый layout. `style.warp.version=1` задаёт совместимый порядок узлов.
- Новые mesh-пресеты записываются как версия 2; старые `mesh` без версии остаются на алгоритме версии 1. Единый fixture проверяет инверсию точки в Python и JavaScript.
- Bbox и маска продолжают управлять распознаванием/очисткой.
- Preview сохраняет старый endpoint и прежний формат для запросов без новых параметров.
- Страница результата в viewer уже содержит старые надписи, поэтому preview должен объединять очищенный crop и RGBA-текстуру до отображения, а не класть полупрозрачный слой поверх старых букв.
- Ограничение текущего окружения: нет `models/` и `config.json`; для точных тестов использовать синтетические изображения и фиксированный текст.

## Constitution Check
Аддитивная сериализация; старые проекты остаются читаемыми; новый движок не вводится; комментарии на русском; тестовые изображения временные.

## Project Structure
- `src/models.py`, `src/components/typesetter.py` — модель, прозрачный RGBA-layer и смещение после layout.
- `src/app/document.py` — план пересчёта: новое положение требует только typeset.
- `src/app/server.py` — preview слоя и координаты.
- `web/js/api.js`, `web/js/viewer.js`, `web/js/editor_session.js` — отображение и undo-жест.
- `tests/unit/test_typesetter.py`, `tests/unit/test_app_server.py`, `tests/e2e/test_ui_smoke.py` — проверка identity, API и drag.

## Implementation Phases
1. Зафиксировать версионируемую модель позиции с identity default.
2. Выделить layer renderer без второго движка текста и без изменения старого рендера.
3. Возвращать layer/bounds/revision и собирать preview без фонового прямоугольника.
4. Добавить drag/cancel/undo и проверить сохранение bbox.
