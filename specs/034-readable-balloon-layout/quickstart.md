# Validation
Запустить venv-release/Scripts/python.exe -m pytest tests/unit/test_bubble_contour.py tests/unit/test_typesetter.py tests/unit/test_text_segmenter.py tests/unit/test_bubble_layout.py.
Затем scripts/eval_balloon_layout.py на локальных output/eval-new-cases; результаты сохраняются в output/layout-study. Сравнить строки, кегль, границы и все три страницы визуально.
