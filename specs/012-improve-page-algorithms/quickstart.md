# Validation
Использовать venv и установленные модели.

`venv/Scripts/python.exe -m pytest tests/unit/test_ocr_fallback.py tests/unit/test_retouch_ink.py tests/unit/test_readable_layout.py tests/unit/test_slanted_layout.py`

`venv/Scripts/python.exe scripts/eval_retouch.py --out output/new-pages-check --ocr rapid --only _007 OperationHousecallP3 3038661 3419871 3923712`

Для сравнения повторить с новым --out и --baseline предыдущего прогона. Не перезаписывать baseline.
