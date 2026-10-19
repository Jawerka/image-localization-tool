# Implementation Plan: Стабильный overlay расширения

**Branch**: `codex/036-inspector-redesign` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary
Заменить wrapper-позиционирование самостоятельным overlay в верхнем слое документа. Вычислять геометрию видимой части изображения для `object-fit`, обновлять её по событиям layout и корректно освобождать ресурсы.

## Technical Context
- Chromium и Firefox extension APIs; основной код в `extension/src/content.js` и `content.css`.
- Не добавлять зависимость Floating UI: текущий lifecycle мал и может использоваться локально.
- Для геометрии учитывать content box, intrinsic ratio, `object-fit` и `object-position`.
- Перемещение DOM узла расширением не должно затрагивать дерево страницы.
- Ограничить наблюдение и обновления; не оставлять постоянный `requestAnimationFrame` после стабилизации.
- Проверка: synthetic Playwright fixtures; ручная проверка Reddit остаётся дополнительной.

## Constitution Check
Минимальный diff; комментарии на русском; локальные сохранённые страницы и пользовательские данные не добавлять.

## Project Structure
- `extension/src/content.js` — lifecycle image records, observers, placement.
- `extension/src/content.css` — fixed overlay layer.
- `tests/e2e/test_extension.py` — сценарии contain, scroll, resize и перенос узла.
- `docs/EXTENSION.md` — ограничения fullscreen/shadow root при необходимости.

## Implementation Phases
1. Добавить воспроизводимый тест с `object-fit: contain` и переносом того же изображения.
2. Добавить расчёт видимого прямоугольника и отдельный overlay без wrapper.
3. Добавить lifecycle обновления/освобождения, проверить циклы и существующий перевод.
4. Проверить поддержку top layer; документировать только ограничения, подтверждённые тестом.
