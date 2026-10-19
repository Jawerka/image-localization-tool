# Implementation Plan: Экономная композиция preview

**Branch**: `043-preview-compose` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary

Убрать из режима transparent layer ненужную полноразмерную сборку страницы. Preview получает RGBA-слой, смешивает его с небольшим crop исходника и выдаёт те же декодированные RGB-пиксели.

## Technical Context

**Language/Version**: Python 3.10–3.13  
**Primary Dependencies**: Pillow, NumPy, pytest  
**Storage**: Нет; операции in-memory.  
**Testing**: `.\\venv\\Scripts\\python.exe -m pytest tests/unit/test_typesetter.py tests/unit/test_app_server.py -q`  
**Target Platform**: Desktop preview, Windows/WebView2 и поддерживаемые Python платформы  
**Project Type**: Desktop app + Python renderer  
**Performance Goals**: Peak RSS снижается; медиана не хуже полного композиционного пути более чем на 5%.  
**Constraints**: `Typesetter.render` и экспорт остаются без изменений; точные декодированные пиксели обязательны.  
**Scale/Scope**: Два renderer файла и профильные тесты.

## Constitution Check

- Пайплайн v2 не меняется; применяется существующий renderer.
- Настройки и зависимости не добавляются.
- Изменение локально, без новых постоянных артефактов.
- Pixel identity и память измеряются до принятия оптимизации.

## Project Structure

```text
src/components/typesetter.py       # render_layer без финальной сборки полной RGB-страницы
src/app/server.py                  # композиция preview в границах crop
tests/unit/test_typesetter.py      # идентичность слоя и полной композиции
tests/unit/test_app_server.py     # API preview против полного результата
specs/043-preview-compose/         # spec, research, plan, tasks
```

**Structure Decision**: Изменяется существующий Typesetter и текущая ветка API preview; новый backend не нужен.

## Research and Decisions

- Полное `Typesetter.render` остаётся прежним и строит итог для экспорта.
- `render_layer` вызывает общую раскладку без финального `alpha_composite(canvas, overlay)`; его вызывающий preview смешивает слой на вырезке исходника.
- Координаты crop — объединение bbox региона и alpha bounds слоя с clipping границ страницы.
- Сравнение на листе 2500×3500 фиксировано в [research.md](research.md); три прогона показали меньший RSS и более быструю медиану.

## Implementation Tasks

1. Разделить расчёт overlay и финальную композицию, не меняя контракт полного `render`.
2. Собирать crop preview непосредственно на исходной вырезке и сохранить origin/clip.
3. Проверить полное pixel equality и сравнить RSS/время на повторяемом крупном сценарии.

## Risks and Mitigations

| Риск | Влияние | Снижение |
|---|---|---|
| Сдвиг слоя при отрицательном origin или выходе за страницу | Ошибка видимого preview | Crop bounds ограничиваются страницей; тесты сравнивают полный render |
| Overlay render пропускает эффекты финального canvas | Несовпадение в редакторе | Слой не меняется; полная композиция остаётся в `render`; API тест сравнивает декодированные RGB |

## Open Questions

- Нет. Измеренные результаты и ограничение небольшого числа повторов указаны в research.
