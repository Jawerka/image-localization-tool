# Приёмка кандидата 1.0.1

Дата сверки: 2026-11-01. Source commit `2fdd2266c9da6689f15646d799702debfd751402`. Тег `v1.0.1` указывает на него. Тег `v1.0.0` остаётся на `a283fcf`.

Итог: **1.0.1 опубликован; целостность основного комплекта подтверждена; обязательная приёмка завершена частично; CI содержит неразобранные падения.**

Машинный паспорт: [ACCEPTANCE_1.0.1.json](ACCEPTANCE_1.0.1.json). CUDA (P06) по-прежнему отложена. Пункты без выполненного критерия имеют статус `open` и результат `incomplete`.

## Что подтверждено

- Публичный релиз, не prerelease: https://github.com/Jawerka/image-localization-tool/releases/tag/v1.0.1
- Digest `ghcr.io/jawerka/image-localization-tool@sha256:16a8a0f3f06c3bd5fc8dcb58a51fe96b23c3b1d1ff72b1ec5b894ad7d4d136ab`. Теги только `1.0.1-cpu-full` и `cpu-full`. Анонимный запрос манифеста — 200.
- Одиннадцать SHA256 паспорта совпадают с ассетами GitHub. Повторно скачанные light/full portable, Chromium ZIP, Docker ZIP и history bundle совпали с паспортом.
- Full portable SHA256: `14d26d24172862ff45a02eaedf6a99533d2faf3ccd357e7ba381e574cff98d99`.

## Что не принято

- Q02: offline smoke en↔ru вместо оценки пайплайна и LLM.
- Q06: нет p50/p95, памяти и диска.
- P01: распаковка и запуск EXE, без цикла перевода, правки и экспорта.
- P02: подготовка компонентов light-пакета не проверялась.
- P03: только Windows updater fixture.
- P05: офлайн-шаг Docker workflow не заменяет Compose, volume, обновление и браузерный проект.
- U08: Chromium ZIP и E2E на Windows backend не закрывают Docker backend и профиль обновления.
- H03: сборки из отдельного чистого клона нет.
- H04: публикация байтов не закрывает открытые зависимости.

`SHA256SUMS.txt` релиза `v1.0.0` совпадает с текущими ассетами этого релиза. Отдельной прежней копии файла нет, поэтому историческую неизменность подтвердить нельзя.

Снятие `1.0.0-cpu-full` из GHCR оставляет pull этого тега с ответом 404. Офлайн ZIP 1.0.0 на релизе `v1.0.0` не переписывался. Теги и файлы публикации этой сверкой не менялись.

## CI масок

[Прогон `2fdd226`](https://github.com/Jawerka/image-localization-tool/actions/runs/41294266264): на Python 3.10, 3.11 и 3.13 одинаково `6 failed, 870 passed, 7 skipped`. На 3.12 Ruff (382) не пускает unit-тесты. Flutter, JS, browser E2E и updater fixture прошли.

Падают:

- `test_source_ink_keeps_outline_joined_across_lines` — recall 0.833 при пороге 0.99
- `test_caption_mislabelled_as_bubble_stays_on_letters` — лишних пикселей 2973 при пороге 800
- `test_outlined_glyphs_cover_letters_not_the_crop` — маска `None`
- `test_polarity_prefers_even_strokes_over_larger_artwork` — покрытие 0 при пороге 0.55
- `test_thick_artwork_mass_is_cut_from_letters` — маска `None`
- `test_partial_outline_keeps_unoutlined_words_and_source_ink` — маска `None`

Локально те же четыре модуля на Windows, Python 3.10.11, opencv 4.13.0, numpy 2.2.6: 64 passed. Между `a283fcf` и `2fdd226` менялся CI, не эти модули. На 1.0.0 единственный Linux unit job останавливался на Ruff и до pytest не доходил. Расхождение Windows/Ubuntu в порогах обводки ещё не локализовано до пикселя; пороги и детектор этой сверкой не менялись.
