# Приёмка 1.0.5 — 2026-10-19

**Статус: частичная приёмка. Кандидат не опубликован.** Проверены Flutter-хост,
реальный перевод на одном эталоне, независимая позиция текста, сохранение,
упаковка и экспорт. Не пройдены чистый installer GUI, Linux/systemd, Firefox/Reddit,
cu128 и WebView2/GPU-замер mesh.

## Сборка

- Версия: `1.0.5`.
- Исходники: `main` @ `9302b5f` (`Merge release digest fix`).
- `source_sha`: `16e5ab5c613c0ca44ee42df410d1a98d313556db75794bb22eac2b659bc64792`.
- Windows-сборка: `scripts/build-windows.ps1 -SkipModels -Portable -SkipInno`,
  затем Inno Setup 6 из `%LOCALAPPDATA%\Programs\Inno Setup 6`.
- Модели и runtime в пакет не входят; использован существующий профиль
  `D:\Documents\apps\ImageLocalizationTool` (копия данных, пользовательский
  профиль не изменялся).

## Артефакты

| Файл | Размер | SHA-256 |
|---|---:|---|
| `ImageLocalizationTool-1.0.5-windows-x64-setup.exe` | 68 070 165 | `5af46149775456bd3d2b02a6ae6f3c7cff4306635e34ffb0256a382b8dd964ba` |
| `ImageLocalizationTool-1.0.5-windows-x64-portable.zip` | 104 997 252 | `0b3824597634d6619aeb7bfeba2b2ee9858e58a4501f353724c32a2f9e6df482` |
| `ImageLocalizationTool-1.0.5-server-win64.zip` | 92 539 468 | `4a60874fbbbbefc73fa0eb75b2166c577c8742de41564d5c27e9e540f2c14969` |
| `ilt-runtime-manifest-1.0.5.json` | 63 722 | `88ed1a288998df86c9d21a5189d4f0483270e7b4799990deffddf925a57eb3d2` |
| `ilt-component-manifest-1.0.5.json` | 8 834 | `0c5b4ed53c7da62d74bc5b6fe6d3c6c3cf295d6b03fcb2ec17b7d628143bc6c7` |
| `ilt-extension-chromium-1.0.5.zip` | 27 556 | `14f47edbac2789e5a8b9808e2fbb331cefaecd5834fe1fa1e0886dde8545195e` |
| `ilt-extension-firefox-1.0.5.zip` | 27 579 | `2a13d44adb30e8b5d168a64480867f1fc41483b97b25ff058eb95f2e0f157b32` |

**Не собран:** `ImageLocalizationTool-1.0.5-server-linux-x64.tar.gz` — нет Bash/WSL
и Ubuntu-хоста; Linux-шаг release workflow остаётся внешним гейтом.

## Что проверено

- **Flutter-хост.** `dist\ImageLocalizationTool\desktop\ImageLocalizationTool.exe`
  запущен с копией профиля; sidecar поднялся, `/api/bootstrap` вернул
  `version=1.0.5`, `models_ready=true`, `llm.ok=true`, `device_effective=cuda`,
  runtime `argos`, `torch-cpu`, `torch-cu130`.
- **Реальный перевод.** Страница `165d82c0` (6 регионов) обработана через тот же
  sidecar: VLM OCR 6 блоков, LLM перевёл 6 блоков. Тайминги: detect 0.585 с,
  OCR 14.827 с, translate 13.918 с. Строки `worker.log`: 19:57:30 и 19:57:44.
- **Независимая позиция текста.** Для региона 1 записан
  `text_position=[2040.0, 482.0]`; `bbox` остался `[1821, 374, 404, 198]`.
  Перевод `Причина ✓` сохранён в версии 5 и прочитан после перезагрузки.
- **Упаковка и повторное открытие.** `acceptance-1.0.5.ilt.zip` — 27 570 416 байт;
  после `package/load` перевод и `text_position` сохранились.
- **Экспорт.** `0001_SecretReport19.png` — 9 331 811 байт; декодированные пиксели
  совпали с `result.png` (`ImageChops.difference` → `None`).
- **Тесты.** Python unit 600, integration 7 (+1 skipped), JavaScript 50, Chromium UI
  14, Flutter analyze без замечаний, Flutter tests 131, Windows updater harness,
  `verify-build` после сборки.

## Что не проверено

- **GUI-клики.** Проверен запуск Flutter-хоста и API-маршрут; автоматизированного
  клика по виджетам установленного EXE нет.
- **Чистый installer GUI и чистая подготовка компонентов.** `setup.exe` собран,
  но не установлен на чистую машину/VM; это отдельный гейт 032/044.
- **Linux/systemd.** Нет Linux-сборки и приёмки на чистом хосте; 045 T010.
- **Firefox и живой Reddit.** Синтетический Chromium пройден, живой Firefox —
  отдельный гейт 037.
- **cu128.** Повторная приёмка на Windows не выполнялась; cu130 принят в 033.
- **WebView2/GPU mesh.** Локальный Flutter mesh preview реализован как черновик;
  p95/GPU memory и визуальная приёмка 039 T001 не выполнены.
- **Гонка экспорта.** Если запустить экспорт сразу после `PUT` документа, пока
  `apply_document` ещё в очереди, экспорт может использовать предыдущий
  `result.png`. Повторный экспорт после завершения очереди был пиксельно
  идентичен. UI должен дожидаться завершения правок перед экспортом.

## Решение

Это **не** принятый релизный кандидат: отсутствуют Linux-артефакт и платформенные
приёмки. Тег и публикация не выполнялись. Следующие шаги: Linux-сборка в Ubuntu,
чистая установка `setup.exe`, Firefox/Reddit, cu128 и WebView2/GPU-замер.
