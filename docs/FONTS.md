# Роли шрифтов (автоподстановка)

Источник правды для кода: [`src/components/font_catalog.py`](../src/components/font_catalog.py)
(`FONT_ROLE_*`, `role_font_id`, `assign_stylized_fonts`). Флаг `auto_stylized_fonts`
(настройка «Автошрифты для SFX/стиля») включает запись `font_id` по этой таблице.
Выключен — поведение как раньше: Heroika только в баллоне, free без CC0-пробы.

Все перечисленные CC0 — GGBotNet, CC0 1.0, с кириллицей. Heroika — OFL.
Jupiteroid Light: <https://ggbot.itch.io/jupiteroid-font>; Novem:
<https://ggbot.itch.io/novem-font> (оба CC0, файлы в `src/resources/fonts`).

## Автовыбор (что ставит пайплайн)

| Ситуация | Шрифт | Почему |
|----------|--------|--------|
| Диалог / нарратив **в баллоне** | **Heroika-Regular** | Привычный comic lettering, читается в пузыре |
| `sfx` (обычный удар/звук) | **DeltaBlock-Regular** | Жирный блочный display, «БУМ/BOOM» |
| `sfx` со смехом (`ха`, `ha`, `хи`, `lol`…) | **Unsightly** | Ломаный comedy-стиль |
| `sfx` «технический» (много цифр / короткий код) | **Liber-Struct** | Геометрия FontStruct, не «взрыв» |
| `title` | **Jupiteroid-Light** | Спокойный геометрический display вместо тяжёлого Blaec |
| free **ALL CAPS** | **Blaec-Regular** | Тяжёлый shout/заголовок |
| `sign` + ALL CAPS | **OperationNapalm-Regular** | Трафарет/предупреждение |
| Free / `sign` / `noise` без капса | **FirstTimeWriting** | Рукопись, заметки, мягкий free-текст |
| Регион уже с `font_id` или `edited` | не трогаем | Ручной выбор важнее |

## Каталог: куда уместнее вручную

| Шрифт | Роль | Уместно | Не уместно |
|--------|------|---------|------------|
| **Heroika-Regular** | dialogue | Речь и мысли в баллоне | Крупные SFX на фоне |
| **FirstTimeWriting** | handwritten | Заметки, дневник, мягкий free | Удары, крики, титры |
| **DeltaBlock-Regular** | sfx | Взрывы, удары, короткий звук | Длинные фразы в баллоне |
| **Liber-Struct** | sfx tech | Механика, UI-шум, «робот» | Рукопись, тёплый диалог |
| **Unsightly** | sfx comedy | Смех, глупый эффект | Серьёзный экшен, диалог |
| **PublicPixel** | sfx pixel | Крупный 8-bit / UI-пиксель | Длинный текст, мелкий кегль |
| **Pixelzone** | sfx pixel | Читабельный pixel, цифровой знак | «Живой» рукописный free |
| **Blaec-Regular** | shout | Крик, CAPS free | Мелкий диалог |
| **Blaec-Italic** | shout | Скорость, наклон, «СКОРЕЕ!» | Спокойная речь |
| **Jupiteroid-Light** | title | Заголовки, титры, обложки | Крик, мелкий диалог |
| **Novem** | title (запас) | Стилизованные/SF-заголовки | Универсальный текст |
| **OperationNapalm-Regular** | shout stencil | Таблички, DANGER, военный тон | Рукопись, нежный текст |
| **VyazPixel** | decor | Декор/титры «под старину» (по желанию) | Автопо умолчанию не ставим |

## Запас (OFL, не CC0)

`FONT_PACK` в `model_manager` (PT Sans, Russo One, Marck Script, Creepster) остаётся
в каталоге пользователя/моделей как ручной выбор. Автопроба на них не опирается.

## Как менять план

1. Обновить таблицу здесь и константы `FONT_ROLE_*` / `role_font_id` в `font_catalog.py`.
2. Подтянуть unit-тесты `test_assign_stylized_fonts_*`.
3. Не размазывать эвристики по `typesetter` / UI — только `role_font_id`.
