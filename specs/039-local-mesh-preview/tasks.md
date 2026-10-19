# Tasks: Локальный preview mesh

## Phase 1: Измерение renderer
- [ ] T001 Сравнить PixiJS MeshPlane и минимальный WebGL на одной прозрачной текстуре 800×400 с кириллицей/обводкой; записать p50/p95, память, браузер и GPU.
- [x] T002 Зафиксировать решение по renderer и воспроизводимую методику; WebView2 остаётся отдельным gate, если доступен только Chromium.

## Phase 2: Исходный слой
- [x] T003 Добавить режим RGBA base-layer preview с origin/revision без изменения проекта и очистки страницы.
- [x] T004 Добавить viewer renderer, который обновляет геометрию поверх исходного кадра и всегда использует неизменённую текстуру на протяжении жеста.
- [x] T005 После pointerup запрашивать точный Typesetter preview; устаревшие ответы не подменяют новый draft.

## Phase 3: Взаимодействия и качество
- [x] T006 Показывать действительные кривые mesh, поддержать групповое перемещение выбранных узлов, Shift-симметрию и сброс узла. Chromium e2e проверяет выбор группы, drag, undo/redo, симметрию и двойной щелчок.
- [x] T007 Отклонять invalid mesh до записи документа с объясняющим сообщением; добавить context-loss fallback. Invalid-cell и потеря WebGL-контекста проверены Chromium e2e; после потери canvas скрывается, точный preview снова видим. Это не заменяет WebView2 performance acceptance T001.
- [x] T008 Проверить один undo на жест, отмену Esc/pointercancel, zoom, exact-vs-export и инспектор при ширине 344 px в двух темах. Undo/redo для одиночного узла и группы, zoom, 344 px и темы проходят Chromium UI suite; отдельный mesh drag cancel тест проверяет Esc/pointercancel; API/Typesetter pixel test сравнивает exact-preview crop с полноразмерным render mesh v2.

## Dependencies
T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008.
