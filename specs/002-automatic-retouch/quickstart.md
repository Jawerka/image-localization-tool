# Проверка

1. До изменений: `venv/Scripts/python.exe scripts/eval_retouch.py --out output/retouch-v2/baseline`.
2. После: `venv/Scripts/python.exe scripts/eval_retouch.py --out output/retouch-v2/current --baseline output/retouch-v2/baseline --reference`.
3. Быстрый прогон: добавить `--only 01-- c000679664f6f76632d07cfbdd08e169 3923336`.
4. Сравнить каждую строку eval.json и clean.png с baseline/reference, включая контуры и края букв.
5. Запустить pytest для segmenter, adaptive_text, sfx_ink, lama_inpainter и page_pipeline; затем общий набор, если нет внешних блокеров.

Нужны локальные модели и test-img. Damage вне зон может считать очистку всего баллона/подписи повреждением; отклонения требуют интерпретации. Результаты не входят в git.
