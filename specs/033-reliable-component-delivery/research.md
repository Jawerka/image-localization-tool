# Research

## Каталог
Decision: готовые сводки обеих платформ в locks/runtime-catalog.json, отдельная явная команда обновления. Release не вызывает resolve.
Rationale: текущий генератор каждый раз меняет транзитивный набор. build-runtime-manifest пишет release до merge старого bundled; Final меняет манифест после упаковки. Требуется одинаковая финальная копия до сборок.
Alternatives: pip/venv на машине пользователя и собственные гигантские архивы усложняют установку/выпуск.

## Загрузка
Decision: SHA256-кэш, сохранение .part, строгая обработка 200/206/416, bounded retries 408/429/5xx; глобальный installer OS-lock.
Rationale: текущие .parts удаляются даже после сетевого сбоя; model_manager не проверяет хэши.

## Активация
Decision: ревизии + активный указатель, проверка в subprocess; диагностический статус без импорта torch в parent.
Rationale: sidecar сейчас импортирует torch через status и установка не может безопасно менять DLL. Worker уже активирует runtime в spawn. Нужен новый worker перед следующей обработкой.

## Ресурсы
RapidOCR 3.9.2 использует PP-OCRv6 и params Det.model_path/Cls.model_path/Rec.model_path.
Argos wheel: 42269 bytes, b0fa2c47dcede945d9a8edbb6845de9b25791faa363bfff0b89fefaea28241f7; происхождение git 17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88.
Argos en→ru 1.9: официальный индекс указывает argos-net.com; доступность и контрольная сумма устанавливаются по реальному артефакту, не угадываются.
Подтверждены реальные загрузки en→ru (195746693 байт, SHA591d743ae103752b88ffc38785c50421320f4eff93c8967e0d3d2e14d4e27811) и frozen OCR/LaMa. Argos использует settings.package_dirs; ARGOS_TRANSLATE_PACKAGE_DIR задаёт legacy-путь, актуальная переменная — ARGOS_PACKAGES_DIR. Для совместимости выставляются обе, MiniSBD выбирается явно до импорта Argos.
Модели RapidOCR/детектора проверяются по локальным файлам и official revision/metadata.

## Интерфейс и пути
Мастер сейчас выбирает языки после загрузок, SSE reconnect не обновляет снимки. Новая очередь должна сохранять selection, items и catalog hash. src/app/paths.py уже разделяет data_root/install_root, но runtime/models/fonts пишут в install_root. Подключить единый component-root и читать legacy. models_dir передать из AppSettings в Config и конструкторы.

## Релиз и CUDA
cu130 cp310-win существует в официальном PyTorch index, CUDA 13 требует драйвер family 580+. Записи и хэши получить при явном обновлении; реальную готовность подтверждать операцией.
Лок cu130 получен реальным генератором: torch2.11.0+cu130, 10 колёс, 1925.4 МБ. Пути ревизий сокращены до24 символов после ошибки загрузки SentencePiece DLL в длинном Windows-пути; полный SHA остаётся в marker/pointer.
Исследование выполнено тремя read-only research agents согласно speckit-plan; их findings учтены в дизайне. Независимое зеркало требует отдельного хостинга.
