# Implementation Plan: Локальный preview mesh

**Branch**: `codex/036-inspector-redesign` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary

Сравнить PixiJS MeshPlane с небольшим WebGL renderer на одинаковой прозрачной текстуре; выбрать решение по p50/p95/памяти. Затем подключить исходный RGBA-слой Typesetter к viewer и оставить точный серверный preview финальной проверкой.

## Technical Context

- Viewer — ES modules без frontend bundler; app запускается в WebView2.
- Python и JS mesh v2 уже имеют общие численные fixtures.
- Рендерер должен принимать исходный RGBA и обновляемые позиции вершин, не перерисовывая текстуру из деформированного кадра.
- Точный серверный preview уже возвращает origin и revision; API расширяется аддитивно.
- Верификация: Node tests, pytest/API и Playwright UI smoke; WebView2 benchmark требуется отдельно от headless Chromium.

## Decisions

- Сравнить PixiJS и минимальный WebGL в отдельном benchmark, не добавляя Pixi в runtime до результата.
- Локальный preview получает новую неизменяемую текстуру при изменении текста/шрифта/размера/цвета и переиспользует её в течение drag.
- Invalid mesh проверяется до commit; точный ответ revision-scoped.
- WebGL context loss переключает renderer в безопасное состояние и запрашивает точный серверный preview.

## Phases

1. Benchmark PixiJS MeshPlane и минимального WebGL на одинаковом RGBA слое; сохранить окружение, результаты и ограничения.
2. Добавить endpoint режима базового RGBA слоя с origin/revision, затем локальное отображение warp v2 без накопления ресэмплинга.
3. После pointerup применять точный revision preview и проверять соответствие экспорту.
4. Добавить кривые mesh, редактирование группы узлов, symmetry/reset и invalid-mesh feedback.
5. Проверить клавиатурный вход, узкую панель, темы, сохранение текста при повторном переводе.

## Risks

- CPU/GPU frame timings headless браузера не равны WebView2 на ноутбуке; финальные цифры не объявлять без согласованного WebView2.
- Явное forward mapping должно точно повторять Python inverse mapping и порядок rotation/warp/translation.
- Alpha premultiplication и цветовой профиль могут дать различия по краям; сверять decoded RGBA.
