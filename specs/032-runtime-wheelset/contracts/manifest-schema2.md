# Contract: Manifest schema 2

**Feature**: 032-runtime-wheelset

Манифест рантайма — релизный ассет `ilt-runtime-manifest-<app>.json` и встроенная копия в базе.
Потребители: `src/app/runtime.py` (клиент), `scripts/check-release.py` (гейт), UI (`/api/runtime`).

## Формат

```json
{
  "schema": 2,
  "app": "1.0.1",
  "packs": [
    {
      "id": "torch-cu128",
      "title": "PyTorch CUDA 12.8 (NVIDIA)",
      "kind": "torch",
      "os": "win",
      "arch": "x64",
      "python": "310",
      "version": "2.11.0+cu128",
      "format": "wheels",
      "size_bytes": 2748779069,
      "driver_min": 570,
      "files": [
        {
          "name": "torch-2.11.0+cu128-cp310-cp310-win_amd64.whl",
          "url": "https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp310-cp310-win_amd64.whl",
          "sha256": "0123…abcd",
          "size_bytes": 2164260864
        }
      ]
    },
    {
      "id": "argos",
      "title": "Argos Translate (офлайн-перевод)",
      "kind": "argos",
      "os": "win",
      "arch": "x64",
      "python": "310",
      "version": "1.11.1",
      "format": "wheels",
      "size_bytes": 41943040,
      "files": [
        {
          "name": "argostranslate-1.11.1-py3-none-any.whl",
          "url": "https://github.com/Jawerka/image-localization-tool/releases/download/v1.0.1/argostranslate-1.11.1-py3-none-any.whl",
          "sha256": "abcd…0123",
          "size_bytes": 42291
        }
      ]
    }
  ]
}
```

## Правила

1. `schema` — строго `2`; записи без `format` и с `url`/`sha256` читаются как archive (schema 1, совместимость).
2. Клиент принимает только записи текущих `os` и `python`.
3. Wheels-запись: `files` непуст; `size_bytes == сумме files[].size_bytes`; каждый `sha256` — 64 hex;
   каждый `size_bytes` > 0; `name` уникален внутри записи.
4. URL файлов — абсолютные, https: официальные CDN (PyPI / PyTorch) или ассет этого релиза
   (собранное колесо `argostranslate` из официального git-пина); GitHub URL-база к файлам
   остальных колёс не применяется.
5. Archive-запись: `url` + `sha256` (верхнего уровня), поведение 1.0.0.
6. Манифест адресуется по версии приложения; фоновое обновление тянет манифест той же версии
   (`releases/download/v{__version__}/ilt-runtime-manifest-{__version__}.json`).
7. `ILT_RUNTIME_MANIFEST_URL` переопределяет источник манифеста (своё зеркало); формат тот же.

## Валидация гейта (Tier 1)

- все правила п.3–5 для каждой записи, иначе exit 1 с адресом записи;
- HEAD каждого URL: HTTP 200; при наличии `Content-Length` он равен `size_bytes` файла;
- недоступный URL (сеть) — ошибка; 404/403 — ошибка.
