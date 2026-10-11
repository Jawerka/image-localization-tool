# Feature Specification: Runtime Deployment — паки рантайма (подход ComfyUI)

**Feature Branch**: `030-runtime-deployment`

**Created**: 2026-10-11

**Status**: Draft

**Input**: План «универсальный релиз 1.0.0 с развёртыванием (ComfyUI-подход)»: база без torch/Argos-стека, тяжёлые рантаймы — отдельными `.7z`-ассетами в `<install_root>/runtime/`, скачиваются кнопкой в мастере/настройках или через CLI `--deploy`. CUDA-пак cu128 (RTX 20–50, драйвер ≥ 570). AMD/Intel в 1.0.0 — только CPU. После установки CUDA-пака `device=auto` сам выбирает CUDA (снять frozen→cpu shortcut, fallback cuda→cpu оставить). Argos-рантайм — отдельным паком; языковые модели Argos качает сам в `data/argos-packages` (портативно).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - База работает без паков, деградация честная (Priority: P1)

Пользователь ставит универсальный установщик (~150–200 МБ), открывает мастер: модели скачиваются как раньше, рантайм-паки предлагаются отдельным шагом с размерами и кнопками. Если torch-пак не установлен, очистка LaMa недоступна: инпейнт идёт через OpenCV, в отчёте задания — баннер «Очистка переключена на OpenCV (LaMa недоступна)». Ничего не падает.

**Why this priority**: это фундамент всего релиза: база без torch должна собираться, запускаться и оставаться работоспособной.

**Independent Test**: собрать sidecar без torch (spike, см. research.md) → `GET /api/runtime` показывает паки и `torch_ready=false`; пайплайн на локальной странице завершается, в warnings — баннер про OpenCV.

**Acceptance Scenarios**:

1. **Given** свежая установка без `runtime/`, **When** открывается мастер, **Then** шаг «Компоненты» перечисляет `torch-cpu`, `torch-cu128` (при NVIDIA), `argos` с размерами, статусами и рекомендацией.
2. **Given** нет torch-пака, **When** запускается перевод страницы с `inpainter_backend=lama`, **Then** LaMa фолбэчится в OpenCV, в отчёте — предупреждение, остальной пайплайн не страдает.
3. **Given** пак скачан частично/битый, **When** проверяется sha256, **Then** установка не происходит, `.part` удаляется, SSE отдаёт ошибку с ретраем.

---

### User Story 2 - NVIDIA: рекомендация и установка cu128, auto→CUDA (Priority: P1)

На машине с NVIDIA и драйвером ≥ 570 мастер рекомендует `torch-cu128`, показывает размер (~1.2–1.5 ГБ) и предупреждает о длительности загрузки. После установки и перезапуска sidecar `device=auto` выбирает CUDA: LaMa-инференс идёт на GPU. При сбое CUDA — один retry на CPU (как сейчас).

**Why this priority**: CUDA — главная причина существования пака; без auto→cuda фича бессмысленна.

**Independent Test**: фикстуры `nvidia-smi` (драйвер 566 → cpu, 570+ → cu128); `resolve_device("auto")` с активированным cu128-паком → `cuda`; LaMa-инпейнт на GPU (smoke на RTX 5060, cu128).

**Acceptance Scenarios**:

1. **Given** NVIDIA, драйвер 617, **When** открыт шаг «Компоненты», **Then** `torch-cu128` отмечен «рекомендовано», `torch-cpu` — альтернатива.
2. **Given** NVIDIA, драйвер 530, **Then** рекомендация — `torch-cpu` с пояснением про драйвер.
3. **Given** пак cu128 установлен, **When** запускается LaMa, **Then** `resolve_device("auto") == "cuda"`, в логе — устройство CUDA.
4. **Given** явный `device=cpu` в настройках, **When** идёт инпейнт, **Then** CUDA не используется (пользователь главнее auto).

---

### User Story 3 - Argos отдельным паком, языковые модели сами (Priority: P1)

Пользователь без LLM-сервера хочет офлайн-перевод: в «Компонентах» ставит `argos` (~90–110 МБ) — без torch и CUDA-стека. При первом переводе пары en→ru Argos сам скачивает языковую модель (~150–200 МБ) в `data/argos-packages` рядом с программой (портативно). Без пакета UI показывает «нужен пак Argos или LLM», перевод не молчит.

**Why this priority**: заявленный фолбэк RapidOCR + Argos должен остаться рабочим в 1.0.0.

**Independent Test**: с установленным argos-паком `translator_backend=argos` + `ocr_backend=rapid` даёт перевод; `ARGOS_PACKAGES_DIR` указывает внутрь `data/`; удаление пака возвращает честное предупреждение.

**Acceptance Scenarios**:

1. **Given** argos-пак не установлен, **When** выбран argos-переводчик, **Then** в настройках/отчёте виден текст «требуется пак Argos», перевод не выполняется, оригиналы не теряются.
2. **Given** argos-пак установлен, **When** первый перевод en→ru, **Then** языковая модель скачивается в `data/argos-packages`, перевод идёт.
3. **Given** портативный запуск, **Then** языковые модели лежат внутри каталога программы.

---

### User Story 4 - Сервер: `--deploy` без UI, headless-активация (Priority: P2)

Администратор Linux/Windows-сервера разворачивает `--headless --remote`, затем `ImageLocalizationTool.exe --deploy cpu` (или `cuda`, `argos`, `models`, `all`) — пак скачивается, проверяется, распаковывается; повторный запуск идемпотентен. Headless при старте активирует установленные паки.

**Why this priority**: серверный ассет — часть релиза; без CLI сервер разворачивать неудобно.

**Independent Test**: `--deploy models` скачивает детектор/LaMa/шрифты; `--deploy cpu` — torch-пак; повторный запуск — «уже установлено», exit 0.

**Acceptance Scenarios**:

1. **Given** чистый сервер, **When** `--deploy all`, **Then** скачиваются models + argos + torch-cpu (по платформе) и печатается сводка.
2. **Given** сеть оборвалась, **When** `--deploy`, **Then** exit code ≠ 0, `.part` не остаётся, повторный запуск докачивает с нуля.
3. **Given** пак уже установлен, **When** `--deploy`, **Then** без сети — «уже установлено».

---

### User Story 5 - Портативный режим: всё в каталоге программы (Priority: P2)

Запуск из portable-zip: `data/`, `models/`, `runtime/` — рядом с программой; Argos-пакеты — в `data/argos-packages`; ничего не пишется в `%APPDATA%`/`%LOCALAPPDATA%`.

**Why this priority**: portable-ассет заявлен в релизе; путаница путей даёт «модели скачались, но не видны».

**Independent Test**: распаковать portable-zip в чистый каталог, скачать модель/пак → файлы внутри каталога программы; `AppPaths.portable == true`.

**Acceptance Scenarios**:

1. **Given** `data/` существует рядом с exe, **When** скачивается модель, **Then** она в `<root>/models`, настройки в `<root>/data/settings.json`.
2. **Given** установка в `%LOCALAPPDATA%`, **Then** рантайм-паки лежат в каталоге установки (`runtime/`), а не в профиле.

---

### User Story 6 - Удаление и статусы (Priority: P3)

Пользователь может удалить пак из настроек; UI показывает «установлен / не установлен / скачивается / ошибка», занятый размер, и не даёт ставить `torch-cpu` и `torch-cu128` одновременно.

**Independent Test**: `POST /api/runtime/remove {"id": "torch-cpu"}` возвращает каталог в исходное состояние; повторная установка cu128 заменяет cpu-пак.

**Acceptance Scenarios**:

1. **Given** установлены оба torch-пака (нештатно), **When** открыт статус, **Then** предупреждение о конфликте, активным считается один (порядок: cu128).
2. **Given** пак скачивается, **When** пользователь жмёт «Отмена» (не предусмотрено) — кнопка недоступна; удаление доступно только после завершения.

---

### Edge Cases

- `nvidia-smi` есть, но вернул ошибку/таймаут — рекомендация cpu, без падения.
- Драйвер 570.x — cu128 разрешён (порог ≥ 570).
- Диск кончился при распаковке — каталог `.tmp` удаляется, пак не активируется.
- Антивирус удалил `.pyd` после распаковки — активация ловит ImportError, UI показывает ошибку с подсказкой.
- Одновременные скачивания двух паков — запрещены (очередь из одного).
- Манифест недоступен — используется встроенная копия; установка доступна из известных URL.
- Windows без NVIDIA-драйвера, AMD/Intel — рекомендован `torch-cpu`.
- Linux-сервер: детект через `nvidia-smi`; pack-id `torch-cpu` с `platform=linux`.
- Обновление релиза: манифест с новыми версиями паков; пак с тем же id переустанавливается («обновить»).

## Requirements *(mandatory)*

- **FR-001**: MUST существовать модуль `src/app/runtime.py`: чтение манифеста (URL из env `ILT_RUNTIME_MANIFEST_URL` → встроенная копия), статус (`available`, `installed`, `size_bytes`, `installed_bytes`, `sha256`), скачивание с прогрессом, проверка sha256, распаковка `.7z` (py7zr) в `<install_root>/runtime/<id>.tmp` → атомарный rename в `<install_root>/runtime/<id>`, маркер `pack.json`, удаление.
- **FR-002**: Скачивание MUST выполняться фоновым потоком (один пак за раз), прогресс — через SSE-событие `runtime.progress` (`{id, status, done, total, error}`); повторный `POST /api/runtime/download` для уже идущего пака MUST возвращать текущий статус, не запускать второй поток.
- **FR-003**: Активация паков MUST происходить при старте sidecar (frozen и dev) до первого импорта torch: для каждого установленного пака `site-packages` добавляется в `sys.path` (torch-паки — раньше остальных, cu128 приоритетнее cpu), каталоги `torch/lib` — в DLL-поиск (`os.add_dll_directory` + `PATH`).
- **FR-004**: База MUST включать `stdlib.zip` (полный stdlib текущего Python, ~3 МБ) в `_internal`; при старте frozen-приложения он добавляется в `sys.path` (frozen stdlib неполон — torch требует `timeit` и др., см. research.md).
- **FR-005**: `resolve_device("auto")` MUST возвращать `cuda` при доступном torch с CUDA; shortcut `frozen → cpu` удаляется; fallback `cuda → cpu` при сбое инференса сохраняется; явный `cpu`/`cuda` в настройках — без изменений.
- **FR-006**: MUST существовать `src/app/hardware.py`: детект NVIDIA через `nvidia-smi --query-gpu=name,driver_version --format=csv,noheader` (таймаут 5 с), порог драйвера `>= 570` → рекомендован `torch-cu128`, иначе `torch-cpu`; AMD/Intel/нет GPU → `torch-cpu`; на Linux — тот же `nvidia-smi`; результат кэшируется на процесс.
- **FR-007**: API MUST добавить: `GET /api/runtime` (статус паков + рекомендация железа + `torch_ready`/`argos_ready`/`device_effective`), `POST /api/runtime/download` `{id}`, `POST /api/runtime/remove` `{id}`; SSE `runtime.progress`. Ответы и события — см. `contracts/runtime-api.md`.
- **FR-008**: `GET /api/bootstrap` MUST включать сводку `runtime` (installed ids, recommended id, `torch_ready`, `argos_ready`).
- **FR-009**: CLI сайдкара MUST принимать `--deploy cpu|cuda|argos|models|all` (без окна и без `--api`): `models` — детектор/LaMa/шрифт как `scripts/setup_models.py`, `cpu|cuda|argos` — паки, `all` — models + argos + torch по рекомендации железа; идемпотентно, exit code 0/1, прогресс в stdout.
- **FR-010**: Argos MUST направлять языковые модели в `data_root()/argos-packages` (`ARGOS_PACKAGES_DIR` выставляется при старте и при `--deploy`); при отсутствии argos-пакета переводчик возвращает честную ошибку «требуется пак Argos», UI показывает её.
- **FR-011**: Пути: `install_root()/models` MUST создаваться при первом обращении (модели в портативном режиме — внутри каталога программы); рантайм — всегда `install_root()/runtime`.
- **FR-012**: Flutter-UI MUST: шаг мастера «Компоненты» (после «Модели») с рекомендацией, размерами, кнопками «Скачать» и прогрессом; секция «Компоненты» в настройках; статусы и удаление; конфликт torch-паков запрещён (вторая кнопка недоступна/заменяет).
- **FR-013**: Сборка базы MUST исключать torch/Argos-стек (`requirements-release.txt`, excludes в spec); отсутствие пака даёт баннер про OpenCV, отсутствие argos — предупреждение переводчика (уже есть в пайплайне).
- **FR-014**: Версионирование паков — в манифесте (id, version, платформа, python tag, url, sha256, size); манифест встроен в приложение и публикуется ассетом релиза; обновление манифеста не требует обновления приложения.
- **FR-015**: Безопасность: только https/локальные URL из манифеста; sha256 обязателен; распаковка только в `runtime/`; имена из архива проверяются на path traversal.

## Key Entities

- **Пак рантайма** (`RuntimePack`): `id` (`torch-cpu`, `torch-cu128`, `argos`), `title`, `kind` (`torch`/`argos`), `platform` (`win32`/`linux`), `python` (`310`), `version`, `url`, `sha256`, `size_bytes`, `gpu` (опционально: `nvidia_driver_min`).
- **Состояние пака**: `available`, `downloading`, `installing`, `installed`, `error`; `error` — текст последней ошибки.
- **Манифест**: `{schema: 1, app: "1.0.0", packs: [...]}`.
- **Рекомендация железа** (`hardware.detect()`): `{vendor, name, driver, recommended, reason}`.
- **Маркер установки** `runtime/<id>/pack.json`: `{id, version, sha256, installed_at}`.

## Success Criteria *(mandatory)*

- **SC-001**: База (установщик) собирается без torch, размер setup ≤ 220 МБ (цель ~150–200 МБ); sidecar без пака стартует, страница переводится с OpenCV-фолбэком.
- **SC-002**: После установки cu128-пака на RTX 5060 (драйвер ≥ 570) `resolve_device("auto") == "cuda"` и LaMa-инпейнт выполняется на GPU; повторный запуск не требует действий пользователя.
- **SC-003**: Портативная раскладка: модель, пак, настройки и Argos-пакеты — внутри каталога программы.
- **SC-004**: `--deploy all` на чистой машине разворачивает сервер без UI; идемпотентен.
- **SC-005**: Полный `pytest` зелёный, `flutter analyze` 0 issues, `flutter test` зелёный; новые юниты покрывают manifest/sha/распаковку/детект/resolve_device/CLI/endpoints.

## Assumptions

- torch для паков — 2.11.x (cpu/cu128) под Python 3.10 (релизная сборка; см. research.md).
- `.7z` собираются скриптами релиза (py7zr), распаковка — py7zr, уже в базе.
- Манифест по умолчанию: ассет `ilt-runtime-manifest-1.0.0.json` релиза `v1.0.0` на GitHub; резолв URL — от `__version__`.
- ROCm/AMD-ускорение и Intel-ускорение в 1.0.0 отсутствуют (только CPU).
- LLM-стека в базах нет; Argos-языковые модели не входят в пак (качает сам Argos).
- Инсталлятор и portable не содержат ни `models/`, ни `runtime/` (кроме пустых каталогов раскладки при желании).
