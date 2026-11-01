# История измерений после сплющивания

Опубликованная история `main` начинается с `e113a9e`. Тег `v1.0.0` совпадает с текущим корнем линии 1.0.

Четыре отчёта `docs/examples/runs/*.json` ссылаются на коммит `c498ba2271a2e9470bf2db92774ee2b8719bfbf7`. Этот SHA **нельзя** заменять новым корнем: он описывает происхождение уже снятых измерений.

## Архив старых срезов

Публикация архива — вместе с выпуском 1.0.1, не часть сборки приложения. Объект `c498ba2` есть в рабочей `.git`, но не входит в опубликованный `main`. Обычный `git bundle create file SHA` даёт пустой bundle: нужен именованный ref.

```powershell
git cat-file -t c498ba2271a2e9470bf2db92774ee2b8719bfbf7
git update-ref refs/archive/measurements-c498ba2 c498ba2271a2e9470bf2db92774ee2b8719bfbf7
git bundle create dist/ilt-history-c498ba2.bundle refs/archive/measurements-c498ba2
git archive --format=tar.gz -o dist/ilt-history-c498ba2-tree.tar.gz c498ba2271a2e9470bf2db92774ee2b8719bfbf7
Get-FileHash dist/ilt-history-c498ba2.bundle, dist/ilt-history-c498ba2-tree.tar.gz -Algorithm SHA256
git update-ref -d refs/archive/measurements-c498ba2
```

Проверено 2026-11-01 в отдельном каталоге:

- bundle SHA256 `e62789f9a1cc9637ec014bc9e777a4ec087a3afb1655b2636e1cdce4196443bb`
- tree tar.gz SHA256 `1e554e05678182dc3025ea57da21776a01f88b646d1caf07f83c5901b8d3ac44`
- восстановление: `git init; git pull <bundle> refs/archive/measurements-c498ba2` даёт `c498ba2271a2e9470bf2db92774ee2b8719bfbf7`
- в дереве нет `llm-api-key`, `.env`, `credentials`, `data/`, ключей

Новый клон получает исходники измерений из этого архива, а не из опубликованного `main`. Старые SHA в `docs/examples/runs` не подменять. Служебные refs и reflog рабочей копии не чистятся ради размера.
