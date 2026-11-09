# Implementation Plan: Более толстая автообводка
**Branch**: codex/010-thicker-outline | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)
## Summary
Добавить классификацию небелого фона в src/components/typesetter.py. Для auto увеличить рассчитанную ширину в 1.75 раза. Один признак используется и callback подбора кегля, и финальной растеризацией. Свободный растр получает временную копию стиля с той же шириной, без изменения сериализованной геометрии.
## Technical Context
Python, PIL, NumPy, существующий v2. Новых зависимостей или Config-полей нет. Целевые unit-тесты и полный локальный прогон 21 страницы с пользовательским LLM.
## Constitution Check
v2 и публичные входы сохранены, комментарии русские, минимальный diff в typesetter; пользовательские данные и результаты только в игнорируемом output. Отдельная ветка, публикация/деплой не выполняются. Качество ограничено этой серией.
## Project Structure
src/components/typesetter.py; tests/unit/test_nonwhite_outline.py; specs/010-thicker-outline; docs/BENCHMARK_RESULTS.md. Локальные before/after, переводы и галерея — output/thick-outline-tests.
## Complexity Tracking
Общий алгоритм цвета/толщины, без нового движка, без перезаписи ручных стилей.
