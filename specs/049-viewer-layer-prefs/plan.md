# Implementation Plan: Состояние слоёв просмотрщика и очередь во вкладке

**Branch**: `049-viewer-layer-prefs` | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md)

## Summary

Добавить в `AppSettings`/`Config` два независимых булевых ключа слоёв с дефолтом `true`, применять их при bootstrap и сохранять каждое переключение через существующий `PUT /api/settings`. Убрать `_BatchBlock` из вкладки «Страницы», оставив его в «Очереди». Обновить Flutter- и Python-тесты.

## Technical Context

**Language/Version**: Dart/Flutter (desktop), Python 3.10+
**Primary Dependencies**: PyQt-независимый `AppSettings`, `IltApi`, `ViewerState`
**Storage**: `data/settings.json` (схема 1), существующий `PUT /api/settings`
**Testing**: `flutter analyze`, `flutter test`, `pytest tests/unit/test_app_settings.py`
**Target Platform**: Windows Flutter EXE, portable `data/`
**Project Type**: Desktop host с Python-сайдкаром
**Performance Goals**: Переключение слоя не блокирует UI; запись сериализуется без потери последнего состояния
**Constraints**: Минимальный diff; не менять формат документа и пайплайн; старые настройки работают без миграции
**Scale/Scope**: `src/config.py`, `src/app/settings.py`, `viewer_state.dart`, `workspace_state.dart`, `pages_rail.dart`, тесты

## Constitution Check

- Пайплайн v2 не меняется: новые ключи только UI-настройки.
- Новая настройка — поле в `Config` со значением по умолчанию.
- Комментарии и docstring — на русском.
- `data/` не попадает в репозиторий; ключ API не затрагивается.
- CLI, окно, расширение и LAN-слушатель остаются на месте.

## Research Summary

Решения записаны в [research.md](research.md). Настройки хранятся в существующем `AppSettings`, отдельное хранилище не вводится. Новых сущностей проекта нет.

## Project Structure

```text
src/
├── config.py                    # два поля с дефолтом true
└── app/settings.py              # нормализация, to_dict, from_dict
apps/desktop/lib/src/
├── state/viewer_state.dart      # восстановление и колбэк изменения слоёв
├── state/workspace_state.dart   # применение bootstrap и сериализованное сохранение
└── ui/pages_rail.dart           # убрать _BatchBlock из «Страниц»
apps/desktop/test/
└── viewer_widget_test.dart      # слои, быстрые переключения, очередь
tests/unit/
└── test_app_settings.py         # дефолты, четыре комбинации, старый файл
```

## Implementation

1. Добавить `viewer_show_boxes`/`viewer_show_mask` в `Config` и `AppSettings`, нормализацию булевых значений, `to_dict`; `from_dict` подхватит их через dataclass-поля.
2. В `ViewerState` добавить восстановление значений без записи и уведомление о смене слоёв из `setShowBoxes`/`setShowMask`; автоматическое включение рамок в `createRegion` использует тот же путь.
3. В `WorkspaceState` при bootstrap применять настройки до `_syncViewerPage`, а изменения слоёв сохранять последовательной очередью в `PUT /api/settings`; ошибку выводить в существующую полосу.
4. Удалить вставку `_BatchBlock` из ветки «Страницы» в `pages_rail.dart`.
5. Обновить тесты: четыре комбинации, старые настройки, кнопки/клавиши/смена страницы/создание региона, быстрые переключения, отсутствие блока очереди на «Страницах».

## Validation

Сценарии записаны в [quickstart.md](quickstart.md). Автоматические проверки: `flutter analyze`, `flutter test`, `python -m pytest tests/unit/test_app_settings.py -q`.

## Complexity Tracking

Отклонений от Конституции нет.
