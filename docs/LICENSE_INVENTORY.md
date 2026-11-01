# Комплект лицензий поставки

Проверка P08. Спорные условия не закрываются догадкой. Готовые ZIP и образ получают файлы через `scripts/pack_notices.py`: `LICENSE`, `LICENSE_INVENTORY.md`, `THIRD_PARTY_NOTICES.md`, `FONTS.md`, `ARGOS_WHEEL.md`.

| Ресурс | Где в пакете | Происхождение | Текст |
|---|---|---|---|
| Код приложения | корень ZIP / `/opt/ilt/LICENSE` | проект | `LICENSE` (MIT) |
| Сводка третьих сторон | корень ZIP | проект | `THIRD_PARTY_NOTICES.md` |
| Argos Translate wheel | `assets/` / runtime | commit `17ed1a9b` | `ARGOS_WHEEL.md`; SHA256 `b0fa2c47dcede945d9a8edbb6845de9b25791faa363bfff0b89fefaea28241f7` |
| Шрифты комплекта | `fonts/`, `src/resources/fonts/` | OFL / CC0 | `FONTS.md` |
| 7-Zip | `tools/7zip/` полного Windows ZIP | установленный 7-Zip сборочного хоста | `tools/7zip/License.txt` |
| Модели детектора/LaMa | `models/` или докачка | каталог компонентов | `src/app/component_manifest.json` |
| RapidOCR ONNX | компонент `rapidocr` | RapidOCR 3.9.2 | тот же манифест, Apache-2.0 |
| Системные Impact / Comic Sans | не упаковываются | ОС пользователя | не часть пакета |

Wheel Argos: путь и SHA берутся из `locks/` и runtime-манифеста кандидата. Сверка SHA выполняется `scripts/check_release.py`.
