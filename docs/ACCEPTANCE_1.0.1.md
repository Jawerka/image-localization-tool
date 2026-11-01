# Приёмка кандидата 1.0.1

Дата записи: 2026-11-01. `__version__` поднят до 1.0.1 до сборки. Тег `v1.0.0` не двигался.

**Кандидат не принят.** Обязательные H02, H03, P07, P08 и живые P01, P02, P05, Q02, Q06, H04 открыты. A07, Q04, Q07, P06 отложены. Паспорт с `implemented`/`deferred`/`blocked*` публикацию не пропускает.

## Стенды и пороги

Среда и пороги до прогона: [EVAL_SET.md](EVAL_SET.md). Сборочный хост — Windows 10 x64 19044, Flutter 3.47.7, Python 3.10.11, Chrome 144. Docker на сборочном хосте отсутствует; контейнер принимается на CT113. Пользовательские установки и production-volume не трогать.

Машинный черновик: [ACCEPTANCE_1.0.1.json](ACCEPTANCE_1.0.1.json). CUDA (P06) — deferred. Публикация не выполнялась.

## Обязательные проверки

| id | статус | команда / среда | ограничение |
|---|---|---|---|
| T01 | tested | `%LOCALAPPDATA%\flutter\bin\flutter.bat analyze/test`, SDK 3.47.7 | `flutter` не в PATH |
| T03 | implemented | CI matrix 3.10–3.13; `test_update_windows.ps1 -Fixture` | полный updater нужен dist |
| T04 | tested | общий fixture Python/JS/Dart | |
| T06 | tested | существующие Host/Origin/secret unit | живой чужой ZIP не сканировался |
| Q01 | implemented | `docs/EVAL_SET.md` | holdout вне git |
| C03 | tested | JS background cache/resume | живой SW Chromium — U08 |
| U07 | tested | widget/e2e smoke + inspector_smoke | живой EXE на 100/150/200% DPI не прогонялся |
| Q02 | deferred | нет живого LLM-прогона кандидата | эталоны локальные; см. BENCHMARK_RESULTS |
| Q05 | tested | unit typesetter/font_catalog | чистые Windows/Linux без системных шрифтов — отдельный стенд |
| U08 | implemented | e2e extension + docs/EXTENSION.md | Firefox экспериментален |
| T02 | implemented | CI job `e2e-browser`, `ILT_REQUIRE_BROWSER=1` | |
| Q06 | deferred | нет замера EXE p95 | пределы не утверждались |
| T05 | implemented | `release.ps1` + `validate_passport` | |
| H02 | implemented | `docs/HISTORY.md`; SHA в runs не менялись | архив не публиковался |
| P07 | implemented | lock-файлы в репозитории | свежий CVE-scan с датой базы — при сборке кандидата |
| P08 | implemented | `docs/LICENSE_INVENTORY.md` | |
| P09 | tested | integration CLI в репозитории | frozen sidecar на чистой машине — с кандидатом |
| P02 | deferred | нет чистого light ZIP прогона | |
| P01 | deferred | нет чистой VM с full ZIP | |
| P03 | implemented | harness; Fixture в CI | реальная установка — с кандидатом |
| P04 | tested | `tests/linux/test_deploy_scripts.sh` | CT113 не разрушался |
| P05 | deferred | нет pull принятого digest на этом шаге | |
| H01 | implemented | spec 001, notes, HISTORY | |
| H03 | implemented | инструкция чистого клона в CONTRIBUTING/HISTORY | отдельный clone не собирался в этой сессии |
| H04 | blocked | нет неизменяемой сборки 1.0.1 | публикация отдельным поручением |

## Сквозной цикл

Перевод → правка → пакет → открытие → сброс → экспорт на целевых поставках остаётся шагом живой приёмки кандидата (H04). D05: `OSError` при записи ZIP не заменяет прежний архив.
