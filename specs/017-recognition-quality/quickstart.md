# Проверка

Локальное окружение: `venv/Scripts/python.exe`.

- Свежий проход шести страниц: `output/recognition-20261114/run.py`; требует подтверждённого сервера пользователя, не передаёт API-ключ.
- Повторная очистка и вёрстка на сохранённых OCR: `output/recognition-20261114/rerender.py <stem> force`; по одной странице на процесс для ограничения памяти.
- Выборочная регрессия восьми старых страниц: `output/recognition-20261114/regression.py`; маски до/после, без нового OCR.
- Итоговая галерея: `output/recognition-20261114/index.html`.
- Профильные тесты и интеграция: test_retouch_ink, test_text_segmenter, test_adaptive_text, test_bubble_layout, test_slanted_layout, test_readable_layout, test_vlm_ocr и tests/integration/test_page_pipeline.py.

Стенды и изображения локальные, в git не включаются. Отчёты не содержат ключей; настройки приложения не изменяются. Для воспроизведения нужен тот же локальный набор и установленные модели.
