# Проверка
1. venv/Scripts/python.exe -m pytest tests/unit/test_retouch_ink.py tests/unit/test_text_segmenter.py
2. Сравнить фиксированные маски до/после; эталон открывать только после сегментации.
3. venv/Scripts/python.exe src/main.py test-img/3419871.png output/3419871-check/final.png --llm-url http://192.168.88.37:8989/v1 --debug-dir output/3419871-check/final-debug
4. Осмотреть остатки букв, градиенты, края облачков и русский перевод.
