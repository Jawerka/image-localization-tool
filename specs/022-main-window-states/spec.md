# Feature Specification: Main Window Container Screens (Empty / Editor / Batch)

**Feature Branch**: `022-main-window-states`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: Plan: Flutter host ports `web/mockups/next` screens. This feature fixes the 022–025 split: **022 = main window container states** (empty, editor, chapter in batch), **023 = viewer/scene** (after a mandatory jank spike), **024 = inspector**, **025 = secondary screens** (settings, glossary, export, remote, style, sfx, batch-run report, first-run), dialogs and modal file flows. Mechanics: `ChangeNotifier` only, tokens checked against `web/tokens.json`, REST/SSE from 021. Scene shows a page-card placeholder here; real page rendering is 023. Inspector rail renders header + awaiting states; region cards are 024.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Empty window: open a chapter (Priority: P1)

With no project open, the window shows a drop zone («Перетащите сюда главу», actions «Открыть файлы…», «Открыть папку…»), the recent projects list with «Очистить», and disabled «Перевести»/«Экспорт». Opening files or a folder creates the project server-side and the window switches to the editor container with the imported pages listed.

**Why this priority**: Nothing else can be reached without acquiring a project; this is the entry state of the app.

**Independent Test**: Widget test pumps the empty state and asserts drop-zone actions and recent rows; a state test asserts the import flow posts the picked path and applies the collection payload; manual run opens a test folder from an empty host.

**Acceptance Scenarios**:

1. **Given** no open project, **When** the shell is ready, **Then** the scene shows the drop zone, «Недавние проекты» (or its empty state), the pages rail shows «Нет открытого проекта» and the dock is hidden.
2. **Given** the empty state, **When** the user picks files via «Открыть файлы…», **Then** each path is imported through the API and the editor container renders the resulting pages (numbers, names, statuses).
3. **Given** the empty state with a non-empty recent list, **When** a recent entry is activated, **Then** that project opens and its pages render.
4. **Given** the empty state, **When** «Очистить» is pressed, **Then** the recent list is emptied server-side and the section shows its empty text.

---

### User Story 2 - Editor container over real pages (Priority: P1)

With a project open, the app bar shows the project name and page count, the language chip «EN → RU», the mode segment «Отбор | Ретушь | Прогон», «Перевести»/«Экспорт»/«Настройки»; the pages rail lists real pages (thumbnail placeholder, number, name, status text, progress for running rows, selection, chapter headings when chapters exist, search, footer «N из M готово» + «Перевести всё»); the scene hosts a page card (name/status chips) that 023 replaces with the viewer; the inspector rail shows its header with an awaiting state; the dock shows tool placeholders; the status bar shows LLM/device chips. Page rows update live from `/api/events`.

**Why this priority**: This is the frame every later screen plugs into; it is independently demonstrable (open a chapter, see statuses, start translation).

**Independent Test**: State tests apply `bootstrap`/`page.updated` payloads and assert row fields; widget test pumps a ready workspace and asserts the pages list, footer counters and app-bar actions; manual run with a test folder.

**Acceptance Scenarios**:

1. **Given** a project with pages, **When** the editor renders, **Then** every page appears with its number, name and status wording («не начата», «в очереди», «идёт N % · этап», «готово», «есть правки», «без LLM», «ошибка»).
2. **Given** a running page, **When** a `page.updated`/`job.progress` event arrives, **Then** the row progress and the footer counters update without a full reload.
3. **Given** idle pages, **When** «Перевести всё» is pressed, **Then** `POST /api/jobs/translate {scope: all}` is issued once and the batch state (US3) becomes visible.
4. **Given** pages with errors, **When** the status filter «Проблемы» is toggled, **Then** only pages needing attention are listed; toggling back restores the full list.
5. **Given** no page selected, **When** «Перевести» (main action) is pressed, **Then** it is disabled with a hint; with an active page it issues `POST /api/jobs/translate {scope: page, page_id}`.

---

### User Story 3 - Chapter in batch (Priority: P2)

While pages are queued/running, the window reflects the batch: app bar job pill «Перевод · N %» with stop, pages-rail batch block (counts done/running/queued/errors, progress bar, «Пауза»/«Продолжить», «Остановить»), the running row shows stage + progress, the dock is disabled with the reason, the scene shows a stage pill, the inspector shows «Страница ещё в работе…», and the footer offers «Повторить ошибки» when errors exist.

**Why this priority**: Batch is a primary workflow, but it only matters after the editor frame exists.

**Independent Test**: State tests drive `job.started/job.progress/job.finished/job.failed` events and assert batch counters and pill text; widget test asserts pause/stop controls; manual run translates a small folder and pauses/resumes.

**Acceptance Scenarios**:

1. **Given** translation started, **When** events stream in, **Then** the job pill percent and the batch counters match `done/queued/running/errors` and the dock controls are disabled with a tooltip.
2. **Given** a running batch, **When** «Пауза» is pressed, **Then** `POST /api/jobs/pause` is issued and the UI shows the paused state; «Продолжить» resumes.
3. **Given** a running batch, **When** «Остановить» is pressed, **Then** `POST /api/jobs/cancel` is issued and queued/running rows return to their pre-run status on the next refresh.
4. **Given** pages with errors after a run, **When** «Повторить ошибки» is pressed, **Then** `POST /api/jobs/retry-errors` is issued and the affected rows leave the error state.

---

### User Story 4 - Frame-level project management (Priority: P3)

The app bar exposes a «Файл» menu (open files/folder, load/save portable project, close project, exit) and pages-rail rows support reorder (drag) and removal (row menu). Closing a project returns the window to the empty state; closing with an unsaved package (409) shows a strip with «Закрыть без сохранения» instead of a modal (modal confirm is 025).

**Why this priority**: Quality-of-life for the container; not required to demonstrate US1–US3.

**Independent Test**: State tests assert `remove-pages`/`reorder`/`package/save` request bodies; widget test asserts the menu items and the dirty-close strip.

**Acceptance Scenarios**:

1. **Given a project, **When** rows are dragged to reorder, **Then** `POST /api/project/reorder` receives the new order and the list keeps it.
2. **Given** a selected row, **When** «Удалить» in its menu is confirmed, **Then** `POST /api/project/remove-pages` is issued and the row disappears.
3. **Given** a dirty package, **When** «Закрыть проект» is pressed, **Then** the 409 answer surfaces as a strip with an explicit «Закрыть без сохранения» action; using it closes via `force`.

---

### Edge Cases

- Import of an empty/invalid folder or archive: the API error is surfaced in the strip; the empty state stays.
- Import while a project is open: pages append to the open project; the list refreshes.
- Stale/renamed recent entries: opened from `recent` ids; a failed open surfaces the error and keeps the empty state.
- Event storm during batch: rows update in place; no full-list rebuild flicker, selection preserved.
- Page status not in the known set: rendered as «не начата» (same fallback as web).
- Project with chapters: chapter headings group the list; pages keep their order.
- Empty project (0 pages): footer shows «0 из 0 готово», translate-all disabled.
- Host language: UI strings are Russian, matching the web app and mockups.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: With no open project the shell MUST render the empty container: drop-zone card in the scene, recent projects list with clear action, pages-rail empty state, inspector awaiting text, no dock, and disabled translate/export actions.
- **FR-002**: File/folder opening MUST use host-side pickers (`file_selector`), and every picked path MUST be imported through `POST /api/import`; folder picking MAY pass `recursive` and chapter mode options in the same request. Cancel MUST be a no-op.
- **FR-003**: Recent projects MUST come from `bootstrap.recent`; activation MUST call `POST /api/project/open-recent {id}`; «Очистить» MUST persist an empty list via `PUT /api/settings {recent_projects: []}`.
- **FR-004**: With a project open the app bar MUST show project name + page count, a language chip «<source> → <target>», the mode segment «Отбор | Ретушь | Прогон», and the translate action with enablement rules (requires a project, an active page and a non-busy host; caret offers «Всё»). The «Экспорт»/«Настройки» buttons are present but disabled with a hint: their dialogs ship in 025.
- **FR-005**: The pages rail MUST list pages from `bootstrap.pages`/collection payloads with number, name, status wording, and progress for running rows, grouped under chapter headings when `chapter` is set, with local search, multi-selection, and per-row context menu.
- **FR-006**: Row status wording MUST match the web client exactly: «не начата», «в очереди», «идёт N % · <этап>», «готово», «есть правки», «без LLM», «ошибка»; stage names are «Детекция», «OCR», «Перевод», «Сегмент», «Маска», «Очистка», «Вёрстка» with a raw-value fallback.
- **FR-007**: The footer MUST show «N из M готово» with a progress bar and, in the batch state, the problem counter; toggling it filters the list to error/overflow pages.
- **FR-008**: Translation MUST be dispatched through `POST /api/jobs/translate` (page/all scopes); pause/resume/stop/retry-errors MUST use `/api/jobs/pause|resume|cancel|retry-errors`; while `busy` the dock MUST be disabled with an explanatory tooltip.
- **FR-009**: The app MUST apply live updates from `/api/events` (`page.updated`, `job.started`, `job.progress`, `job.finished`, `job.failed`, `job.cancelled`, `worker.restarting`, `worker.failed`, `llm.status`) to rows, counters and the job pill without reloading the whole collection.
- **FR-010**: The batch state MUST render a job pill «Перевод · N %» + stop in the app bar, a batch block in the pages rail (counts, progress, pause/stop), a stage pill over the scene, the inspector awaiting state, and «Повторить ошибки» in the footer when errors exist.
- **FR-011**: The scene MUST host a page card placeholder (page name/number, status chips) for 023; the inspector rail MUST render its header with state-dependent awaiting text for 024; no region/viewer functionality is required here.
- **FR-012**: A slim status bar MUST show the batch/selection message and bootstrap-level chips (LLM state, device, version); unknown values render as absent, not as zeros.
- **FR-013**: The «Файл» menu MUST offer open files/folder, load/save portable project (paths obtained via `file_selector`, sent as `POST /api/project/package/load|save {path}`), close project (`POST /api/project/close`), and exit; a 409 dirty answer MUST offer «Закрыть без сохранения» (force) in a strip.
- **FR-014**: Row drag-reorder MUST call `POST /api/project/reorder {page_ids}` with the full new order; removal MUST call `POST /api/project/remove-pages {page_ids}` after an in-row confirmation.
- **FR-015**: State MUST stay `ChangeNotifier`-based (`ShellState` connection owner + `WorkspaceState` data owner) with no new packages; API failures MUST surface as a dismissible error strip, never as a frozen screen.
- **FR-016**: Existing 021 guarantees MUST hold: cookie auth on every call, SSE reconnect, sidecar lifecycle, attach mode, single-instance; `python -m src.app` paths unchanged.

### Key Entities

- **ProjectInfo**: `{id, name, chapter count}` from `project` payloads; null when closed.
- **PageRow**: `{id, name, chapter, status, progress, stage, error, warnings}` from `bootstrap.pages`/collection; merged with live events.
- **BatchCounts**: derived `{done, running, queued, errors, offline, total}` + `paused`.
- **RecentEntry**: `{id, name, path, …}` from `bootstrap.recent`.
- **WorkspaceState**: `ChangeNotifier` owning project, pages, recent, selection, filter, batch and actions; `ShellState` owns the connection and re-notifies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From handshake-ready to rendered editor with a 12-page folder: ≤ 2 s on the reference machine (excluding import time).
- **SC-002**: A `page.updated` event is reflected in the row and footer within 1 s of arrival.
- **SC-003**: «Перевести всё» on a test folder yields the job pill, batch counters and pause/resume/stop round-trips observable in the UI.
- **SC-004**: `flutter analyze` clean and `flutter test` green (widget + state tests for empty/editor/batch); existing pytest and JS suites unchanged.
- **SC-005**: Opening a folder, translating, and closing the project leaves no orphan process and returns to the empty state (manual check).

## Assumptions

- The Python API from 021 already exposes every endpoint used here; no server changes are expected (adjust only if a contract gap is found during implementation).
- 023/024 replace the scene and inspector interiors; their state models will extend the workspace rather than rewrite the shell.
- Mockups (`web/mockups/next`) are the visual reference; exact pixel parity is not required, token parity is (colors, radii, spacing scale from `web/tokens.json`).
- Window drag-and-drop of files is out of scope (single-instance path forwarding covers Explorer opens); the drop zone is an actionable card, not an OS drop target.
