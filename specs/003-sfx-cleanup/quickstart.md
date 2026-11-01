# Проверка

Сохранить действительный анализ: `venv/Scripts/python.exe scripts/eval_masks.py --out output/sfx-review --run baseline --ocr rapid`.

Очистка до изменения: `venv/Scripts/python.exe scripts/eval_sfx.py --regions output/sfx-review/baseline --out output/sfx-review/clean-before`.

После: тот же вызов с `--out output/sfx-review/clean-after --baseline output/sfx-review/clean-before`. Эталон используется только для оценки. `--only sound-ref` ограничивает быстрый прогон.

Проверить реальные PNG и masked coverage/hit отдельно от чтения/ролей. Японский текст и пропуски OCR не объявлять исправленными без соответствующего подтверждения. Выполнить unit SFX, mask/eval, adaptive/segmenter и integration PagePipeline, затем общий Python-набор при необходимости.
