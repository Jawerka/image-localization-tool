# Feature Specification: Secondary Screens & Dialogs

**Feature Branch**: `025-secondary-screens`

**Created**: 2026-10-10

**Status**: Draft

**Input**: Plan: 025 = «контейнерные экраны и диалоги». Split fixed after reviewing `web/mockups/next`: settings, glossary, export, remote, first-run and the dialog set are **screens/overlays of this feature**; `style.html`/`sfx.html` and the `batch-run` report rail are **inspector modes**, so they move to 024 (documented deviation from the 022 spec's tentative list). Export folder picking uses `file_selector` + an explicit-path gap-fix in the API (the server's dialog bridge is a no-op under `--api`). Mechanics: `ChangeNotifier` only, strings and structure follow the mockups, tokens from `web/tokens.json`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Settings (Priority: P1)

From the gear icon, the «Файл» menu («Настройки…») or Ctrl+, a full-window settings screen opens with nine sections (Внешний вид, Перевод, Сервер LLM, Обработка, Вёрстка, Экспорт, Модели, Сеть, О программе). Edits are a draft: theme and UI scale preview live on the shell, «ОК»/«Применить» persist via the API, «Отмена» reverts, «Сбросить к значениям по умолчанию» restores defaults. The LLM section checks the server and lets the user pick a model; the models section shows readiness and downloads missing files with live progress; «О программе» opens the log and data folder.

**Why this priority**: The host currently cannot configure translation at all; every later workflow (LLM, device, fonts, export defaults) depends on this screen.

**Independent Test**: Widget tests pump the screen with a fake workspace state and assert section switching, draft edit/apply/cancel and the reset action; a state test asserts the `PUT /api/settings` body contains only changed keys; manual run checks live theme/scale preview.

**Acceptance Scenarios**:

1. **Given** bootstrap settings, **When** the screen opens, **Then** every section renders its controls with current values (theme radio cards, scale slider 100–150, selects, numbers, switches).
2. **Given** a changed field, **When** «ОК» is pressed, **Then** the host sends one PUT with exactly the changed keys and the shell keeps the new theme/scale.
3. **Given** changed fields, **When** «Отмена» is pressed, **Then** nothing is sent and the shell preview is restored.
4. **Given** «Проверить» in the LLM section, **When** the server answers, **Then** the model list appears and a chosen model lands in `llm_model`.
5. **Given** a missing model, **When** the models section downloads it, **Then** progress updates live from `model.progress` events and finishes as «Готово».

---

### User Story 2 - Export dialog (Priority: P1)

«Экспорт» (button, menu item, Ctrl+E) opens a modal over the editor: scope radio cards (Все / Только готовые / Выбранные with counts), destination folder (read-only path + «Обзор…» via `file_selector`), format segment PNG/JPG, JPG quality, name-conflict select, «Открыть папку после экспорта», a summary line and the primary button «Экспорт N страниц». On completion the shell shows «Сохранено N страниц» and optionally opens the folder.

**Why this priority**: Export closes the primary user journey (open → translate → export) required by the 026 acceptance.

**Independent Test**: Widget test drives the dialog with a fake state and asserts scope counts, disabled states and the export call; a state test asserts the folder is registered through `/api/dialog/directory` and then `/api/jobs/export` carries the chosen parameters; manual run exports a translated test folder.

**Acceptance Scenarios**:

1. **Given** ready pages, **When** the dialog opens, **Then** scope cards show real counts and the summary line reflects format/quality/conflict.
2. **Given** no folder chosen, **When** «Экспорт» is pressed, **Then** the picker opens first (or the button is disabled with a hint) and no request is sent without a folder.
3. **Given** a chosen folder and scope, **When** export runs, **Then** file NNN images appear in the destination and the completion strip reports the saved count.
4. **Given** a project without ready pages, **When** the shell renders, **Then** «Экспорт» is disabled.

---

### User Story 3 - Glossary (Priority: P2)

«Глоссарий…» opens the series glossary: a table (Оригинал / Перевод / Род / Заметка) with search, inline row editing («Изменить», «ОК»), «Удалить», «Добавить строку» and a record counter. Saving persists through `PUT /api/project/glossary` and marks the package dirty.

**Why this priority**: Glossary is a daily translation-quality tool, but not required for the minimal export journey.

**Independent Test**: Widget test edits a row and adds one; state test asserts the PUT body shape; manual check against a project with speakers.

**Acceptance Scenarios**:

1. **Given** a project with speakers, **When** the screen opens, **Then** entries from page documents appear (merged view) with the counter.
2. **Given** an edited row, **When** «ОК» is pressed, **Then** the whole list is sent in one PUT and the counter/search keep working.
3. **Given** an empty original, **When** the row is saved, **Then** it is dropped (same normalization as the server).

---

### User Story 4 - First-run wizard (Priority: P2)

On the first launch (`first_run_complete == false`) a wizard opens over the empty shell: 1 Тема → 2 Модели (with downloads and progress) → 3 Сервер LLM (address + «Проверить» + model) → 4 Языки. «Пропустить всё» or the final «Готово» persist the choices and the completion flag; «Далее»/«Назад» navigate without persistence until the end.

**Why this priority**: Without models the app cannot translate; the wizard is the guided path, though the settings screen can do the same manually.

**Independent Test**: Widget test walks the steps with a fake state; state test asserts the final settings patch (`first_run_complete`, theme, target_lang, llm fields); manual run with a wiped data dir.

**Acceptance Scenarios**:

1. **Given** a fresh install, **When** the shell is ready, **Then** the wizard opens once; after finishing or skipping it never opens again.
2. **Given** the models step, **When** a download is started, **Then** each row shows bytes/percent progress from events and «Готово»/«в очереди» states.
3. **Given** the wizard finished, **When** settings are inspected, **Then** `first_run_complete` is true and the chosen theme is applied to the shell.

---

### User Story 5 - Dialogs: hotkeys, exit, worker failure (Priority: P3)

F1 opens the «Горячие клавиши» dialog with a search field and grouped shortcut tables (Канвас, Файл и проект). Closing the window while pages are queued/running asks «Закрыть приложение?» with «Отмена», «Выйти сейчас» and a «дождаться окончания» option instead of killing work silently. A `worker.failed` event opens the «Не удалось запустить обработку» dialog with the reason, a «Повторить ошибки» action and «Открыть лог».

**Why this priority**: Safety nets and help; the workflows above already work without them.

**Independent Test**: Widget test opens each dialog from the shell and asserts the buttons/actions; manual check of the exit dialog during a run.

**Acceptance Scenarios**:

1. **Given** the shell, **When** F1 is pressed, **Then** the hotkeys dialog opens, filters by query and closes on Esc.
2. **Given** a running batch, **When** the user closes the window, **Then** the exit dialog appears and only «Выйти сейчас» exits.
3. **Given** a `worker.failed` event, **When** the dialog is shown, **Then** its actions requeue failed pages or open the log file.

---

### User Story 6 - Remote access (Priority: P3)

The «Доступ по сети» screen shows the switch «Разрешить доступ в локальной сети», bind/port fields, the listening chip, a pairing code with «Новый код», connected devices with «Отозвать», the HTTP warning and the «Что видит устройство» summary. Enabling persists `remote_enabled` and the UI offers a sidecar restart to apply it (LAN listener is started at sidecar start).

**Why this priority**: LAN is opt-in and less used, but must not regress in the cutover.

**Independent Test**: State test asserts settings patch and pair/revoke calls; manual check: enable → restart → chip shows the address, phone pairs.

**Acceptance Scenarios**:

1. **Given** remote disabled, **When** the screen opens, **Then** the switch is off, the pair-code block is inactive and the warning is visible.
2. **Given** the user enables remote, **When** the sidecar restarts, **Then** `GET /api/remote/status` reports enabled with addresses and a pairing code can be issued.
3. **Given** a connected device, **When** «Отозвать» is pressed, **Then** `POST /api/remote/revoke {id}` runs and the list refreshes.

---

### Edge Cases

- Settings draft + external change: bootstrap is the baseline; «Отмена» restores it; applying sends only touched keys.
- Secret dialog: the key is never displayed (only «задан/не задан» from `has_api_key`); empty input cancels.
- Downloads: already-present model → instant «Готово»; network failure → row error text, retry allowed.
- Export with zero ready pages in the chosen scope: button disabled with the reason.
- Export destination exists with files: conflict mode is honored by the server; the UI shows the mode in the summary.
- Glossary duplicates: server normalization drops repeats; the UI mirrors the returned list.
- First-run with a partially downloaded model set: only missing items are offered.
- Esc closes overlays top-down; while a modal is open the shell shortcuts (V/R/B etc.) do not fire.
- Remote port busy: sidecar logs the failure; the screen shows «не слушает» and the warning.
- Non-Windows host (attach dev): file pickers come from `file_selector`; opening a folder falls back gracefully.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Screens MUST render as full-window overlays (settings, glossary, remote, first-run) and modals (export, hotkeys, exit, worker) above the shell; Esc closes the top overlay; screen-local forms MUST NOT fire shell hotkeys.
- **FR-002**: Entry points: gear icon and «Файл → Настройки…» and Ctrl+, open settings; «Экспорт»/Ctrl+E open export; «Файл → Глоссарий…» opens glossary; F1 opens hotkeys; the remote screen opens from settings (Сеть) and/or the status bar chip.
- **FR-003**: Settings MUST cover the nine mockup sections with these controls: theme radio cards (Тёмная/Светлая/Как в системе), scale slider 100–150, keyboard switches, canvas switches; target language / reading order / sfx mode / glossary path; LLM base URL, model + «Список…», API key «Задать…», «Проверить»; OCR/translator/inpaint selects, device select, detector threshold; layout numbers and default font; export defaults (subfolder/format/quality/conflict); models list with sizes/status/download; remote enable+bind+port; about (version, settings path, data path, «Открыть лог», «Открыть папку данных»).
- **FR-004**: Settings edits MUST be a draft: theme and scale preview on the shell immediately; «ОК»/«Применить» send one `PUT /api/settings` with only changed keys; «Отмена» restores the preview; «Сбросить» loads the bundled defaults into the draft.
- **FR-005**: LLM section MUST call `POST /api/llm/check` and list returned models; selecting one writes `llm_model`; the API key flows through `POST /api/settings/secret` and is never rendered back.
- **FR-006**: Models section (and wizard step 2) MUST read `GET /api/models`, trigger `POST /api/models/download {kind}`, render per-kind progress from `model.progress` events (bytes/percent) and final «Готово»/«в очереди» states; «Открыть папку моделей» opens the directory.
- **FR-007**: Export dialog MUST support scopes Все/Только готовые/Выбранные with counts, `file_selector` folder picking registered through `POST /api/dialog/directory {path}` (server gap-fix), format PNG/JPG, JPG quality, conflict mode, and MUST submit `POST /api/jobs/export`; the export button is disabled when the scope has zero pages or no folder is chosen yet.
- **FR-008**: Export completion MUST be derived from the `job.finished` event carrying the export result (`saved`, `paths`): the shell shows «Сохранено N страниц» and opens the folder when requested.
- **FR-009**: Glossary screen MUST load `GET /api/project/glossary`, allow search, inline edit (Оригинал/Перевод/Род/Заметка), add and delete, and persist the full list via `PUT /api/project/glossary`; empty rows are dropped like the server does.
- **FR-010**: First-run wizard MUST open when `settings.first_run_complete` is false, walk four steps (Тема, Модели, Сервер LLM, Языки), allow «Пропустить всё», and persist `first_run_complete: true` plus the chosen values; it MUST NEVER reopen after completing or skipping.
- **FR-011**: Hotkeys dialog MUST contain the grouped shortcut table from the mockup (Канвас: масштаб/прокрутка/вписать/100 %/кисть/лассо/перевод региона/сдвиг/проблемная страница; Файл и проект: открыть/сохранить/экспорт/перевести страницу/перевести всё/быстрые команды), with a search filter and the footnote about one-letter keys.
- **FR-012**: Closing the window with unfinished pages MUST show the exit dialog; the host exits only on the explicit action; a «дождаться и закрыть» choice exits automatically after the batch finishes (or the current page, matching the server's cancel).
- **FR-013**: A `worker.failed` event MUST open the worker-failure dialog with the event's reason, «Повторить ошибки» (`POST /api/jobs/retry-errors`) and «Открыть лог» (host opens the log file directly — the server dialog bridge is a no-op under `--api`).
- **FR-014**: Remote screen MUST read `GET /api/remote/status`, show enable/bind/port from settings, issue codes via `POST /api/remote/pair-code`, revoke devices via `POST /api/remote/revoke`, and persist the enable/bind/port fields; applying the listener MUST be described as needing a sidecar restart, with a «Перезапустить API» action available.
- **FR-015**: Server contract gap-fixes (only these): `run_api` MUST start the LAN listener when `settings.remote_enabled` is true (mirroring the window mode's `start_remote(force=args.remote)` semantics) and `POST /api/dialog/directory` MUST accept an explicit `path` in the body for the host-picked folder (setting `export_dir`); all other behavior stays untouched.
- **FR-016**: All new state MUST stay `ChangeNotifier`-based with no new packages; the existing shell behavior (022 flows) MUST remain intact; `flutter analyze` clean and `flutter test` green.

### Key Entities

- **SettingsDraft**: local `Map<String, dynamic>` over `bootstrap.settings` with changed-keys tracking and preview callback.
- **ModelStatus**: `{detector, lama, font}` each `{present, path}` + transient download progress `{kind, done, total}`.
- **GlossaryRow**: `{source, target, gender, note}` with client-side validation/normalization.
- **ExportOptions**: `{scope, page_ids, dest, format, jpeg_quality, conflict, open_after, content, archive}`.
- **RemoteStatus**: `{enabled, addresses, pairing_code, devices[], clients}`.
- **OverlayController**: part of `ShellState` (active screen, pending exit request, worker failure payload).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Settings changes apply to the running shell (theme/scale) before saving, and «Отмена» returns the previous look.
- **SC-002**: Export of an 8-page ready chapter completes and the completion strip names the saved count; files land in the chosen folder.
- **SC-003**: Glossary edits survive reopening the screen (round-trip through the API).
- **SC-004**: A fresh data dir shows the wizard once; downloads run with visible progress; the second launch does not show it.
- **SC-005**: F1/Esc/Ctrl+,/Ctrl+E work from the shell; the exit dialog appears only with unfinished pages.
- **SC-006**: Remote enable + sidecar restart makes `remote/status` report enabled; pairing works from a phone browser on LAN.
- **SC-007**: `flutter analyze` clean, `flutter test` green (new widget/state tests included); existing pytest/JS suites untouched and green.

## Assumptions

- Mockups (`web/mockups/next`) are the structural reference; visual polish is bounded by the existing theme tokens.
- The vision-model dialog from `dialogs.html` collapses into the settings model picker: the API (`/api/llm/check`, `llm.status` events) carries plain model names and no vision flags, so no vision badges are shown (documented limitation).
- Hotkey *actions* beyond the ones already implemented (F1/Ctrl+,/Ctrl+E/Esc and the 022 menu shortcuts) are shown in the help table but wired only where the feature exists (viewer hotkeys land in 023).
- LAN listener applies at sidecar restart; a live toggle endpoint is out of scope.
- Tray minimize («Свернуть в трей») from the exit dialog is out of scope (no tray support without new packages); the dialog offers cancel/exit/wait.
