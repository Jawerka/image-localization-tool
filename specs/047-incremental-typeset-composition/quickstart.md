# Quickstart: Проверка частичной композиции

## Требования

- Активное Python-окружение проекта с зависимостями из `requirements.txt`.
- Windows/Linux/macOS; внешние VLM/переводчик для unit и интеграционных тестов не нужны.

## Проверка

```powershell
python -m pytest tests/unit/test_app_document.py tests/unit/test_app_store.py tests/unit/test_typesetter.py tests/unit/test_app_worker.py tests/integration/test_page_pipeline.py
```

Ожидаемый результат: все сценарии проходят; частичный путь сообщает прямоугольник меньше страницы для локальной правки; пиксельный массив совпадает с полной композицией. Случаи без provenance и с большой dirty area используют full fallback и тоже совпадают с эталоном.

Для регрессии приложения:

```powershell
python -m pytest
node --test tests/js/*.mjs
```

## Покрываемые сценарии

- Изменение текста/стиля без clean-пересчёта.
- Перемещение, включая выход за исходный bbox; вращение и mesh v2.
- Перекрывающиеся надписи и изменение пустого/непустого текста.
- Неподходящая версия/fingerprint, отсутствующие bounds, большой dirty rectangle и scaled layout.
