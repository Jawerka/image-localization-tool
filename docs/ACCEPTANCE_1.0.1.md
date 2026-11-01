# Приёмка кандидата 1.0.1

Дата: 2026-11-01. Source commit `2fdd2266c9da6689f15646d799702debfd751402`. Тег `v1.0.0` не двигался.

Кандидат собран `scripts/release.ps1 -Prepare`. Digest: `ghcr.io/jawerka/image-localization-tool@sha256:16a8a0f3f06c3bd5fc8dcb58a51fe96b23c3b1d1ff72b1ec5b894ad7d4d136ab`.

Машинный паспорт: [ACCEPTANCE_1.0.1.json](ACCEPTANCE_1.0.1.json). CUDA (P06) deferred.

## Стенды

Сборочный хост Windows 10 x64 19044, Flutter 3.47.7, Python 3.10.11, Chrome 144. Живой Docker CLI на хосте нет; образ принят по GHCR workflow (`functional --network none`) и digest. LLM-прогон Q02 на этом хосте заменён подготовленным offline en↔ru smoke полного ZIP.

## Ограничения

- CI job unit Python 3.12 падает на существующем `ruff check` (382 замечания); локальный pytest unit 3.10: 882 passed.
- Локального Docker CLI нет; анонимный pull манифеста digest через GHCR token API вернул 200.
- Linux fake-root на Git Bash/Windows некорректен; Linux CI Release успешен.
- Рабочие установки `D:\Documents\apps\ImageLocalizationTool` и распакованное расширение не обновлялись.

## CR12 — публичные загрузки

Повторно скачаны с https://github.com/Jawerka/image-localization-tool/releases/tag/v1.0.1:

- `ImageLocalizationTool-1.0.1-windows-x64-portable.zip` — SHA256 `ea688474…872ff`
- `ImageLocalizationTool-1.0.1-windows-x64-portable-cpu-full.zip` — SHA256 `14d26d24…4e7`
- `ilt-extension-chromium-1.0.1.zip` — SHA256 `4a091b30…e362`
- `ImageLocalizationTool-1.0.1-docker-cpu-full.zip` — SHA256 `c4d93e1a…587b`
- `ilt-history-c498ba2.bundle` — SHA256 `e62789f9…443bb`

Совпали с паспортом и `SHA256SUMS.txt`. Light и full ZIP распакованы в `D:\Documents\apps\ilt-cr12-*`; EXE запускались. Chromium ZIP — `version` 1.0.1. Ассеты `v1.0.0` на месте, `SHA256SUMS.txt` 1.0.0 не изменился. GHCR: одна версия, теги `1.0.1-cpu-full` и `cpu-full`.
