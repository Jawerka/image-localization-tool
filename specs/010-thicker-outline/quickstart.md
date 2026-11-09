# Проверка
1. venv/Scripts/python.exe -m pytest tests/unit/test_nonwhite_outline.py tests/unit/test_typesetter.py tests/unit/test_readable_layout.py tests/unit/test_vertical_sound_layout.py tests/unit/test_unbound_balloon.py tests/unit/test_text_style.py -q
2. Полный локальный прогон: output/thick-outline-tests/run_before.py (VLM/LLM по адресу пользователя).
3. output/thick-outline-tests/run_after.py — тот же перевод/ретушь с новой вёрсткой, без новых LLM-запросов.
4. Осмотреть PNG до/после и отчёт переполнений; проверить белые, цветные и тёмные поля, свободные надписи.
