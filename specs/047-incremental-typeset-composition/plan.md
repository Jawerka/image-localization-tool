# Implementation Plan: Частичная композиция текста

**Branch**: `codex/047-incremental-typeset-composition` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/047-incremental-typeset-composition/spec.md`

## Summary

Добавить инкрементальную композицию для правок только текста, стиля и положения. Перед правкой передавать предыдущий документ только если прежний результат уже готов. Хранить вместе с результатом его версию, отпечаток очищенной страницы и фактические ink-bounds регионов. Если база совпадает, пересобрать безопасный dirty crop из clean-изображения и нового упорядоченного overlay, вставить его в предыдущий результат. При старых/неполных метаданных, изменении reading direction, масштабировании или большой области влияния использовать полную композицию.

## Technical Context

**Language/Version**: Python 3.10–3.13

**Primary Dependencies**: Pillow, NumPy; существующие PagePipeline и Typesetter

**Storage**: `page.json` для metadata результата; существующие `clean.png` и `result.png`

**Testing**: pytest unit/integration с точным сравнением RGB-массивов; существующие UI/API/worker suites

**Target Platform**: Локальное приложение Windows/Linux/macOS, CLI pipeline v2

**Project Type**: Desktop app + Python pipeline + web UI

**Performance Goals**: Для одной непересекающейся правки композировать <=25% пикселей контрольной страницы; пиксели результата совпадают с полной композицией

**Constraints**: Не менять cleaning/OCR/translation semantics; не применять частичный путь к изменению рамок/масок; stale job остаётся отвергнутым по версии документа; прежние проекты без render metadata должны автоматически перейти через full path

**Scale/Scope**: Один документ страницы, произвольное число регионов, операция локальной правки

## Constitution Check

- **Пайплайн v2**: Pass. Используется текущий Typesetter/PagePipeline, новый путь не обходит pipeline.
- **Минимальный diff**: Pass. Изменения ограничены diff-planning, worker job, Typesetter, ProjectStore и тестами; отдельный rendering engine не вводится.
- **Русский язык**: Pass. Новые комментарии/docstring на русском.
- **Локальные данные**: Pass. Fingerprint — SHA-256 очищенного файла; сторонние изображения и пользовательские тексты не пишутся в логи.
- **Заявленное качество**: Pass. Требуется точная пиксельная идентичность на фиксированных синтетических сценариях; результаты не экстраполируются на произвольные страницы.
- **Границы совместимости**: Pass. CLI, HTTP и документный формат сохраняют чтение старых страниц; metadata добавляются как необязательные поля.

## Research Decisions

- См. [research.md](research.md): фактические bounds берутся от финального rasterized слоя, включая вращение и warp; old result допускается только при совпадении result-version и SHA-256 clean; большой или ненадёжный crop уходит в полный renderer.

## Project Structure

```text
src/app/document.py             # определить ids затронутых typeset-регионов
src/app/server.py               # приложить предыдущий документ к безопасной правке
src/app/store.py                # сохранять provenance результата и region bounds
src/app/worker.py               # выбрать incremental path либо полный fallback
src/page_pipeline.py            # применять partial composition без повторной очистки
src/components/typesetter.py    # собирать overlay и финальные bounds каждого региона
 tests/unit/test_app_document.py
 tests/unit/test_app_store.py
 tests/unit/test_typesetter.py
 tests/unit/test_app_worker.py
 tests/integration/test_page_pipeline.py
specs/047-incremental-typeset-composition/
```

**Structure Decision**: Изменить существующий pipeline v2 и хранить служебную provenance рядом с метаданными страницы; внешний HTTP-контракт не меняется.

## Complexity Tracking

Нет отклонений от конституции.
