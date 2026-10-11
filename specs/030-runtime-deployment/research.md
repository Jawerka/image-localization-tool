# Research: 030-runtime-deployment

**Date**: 2026-10-11

## Spike: frozen sidecar без torch + внешний пак

Установка: PyInstaller 6.22.3, Python 3.10.11 (venv-release), PyInstaller-браузер без torch
(все импорты torch — динамические, `importlib.import_module("tor" + "ch")`), внешний каталог
`site-packages` с torch 2.11.0+cpu/собранными зависимостями, активация:

```python
sys.path.insert(0, pack / "site-packages")
os.add_dll_directory(pack / "site-packages" / "torch" / "lib")
```

Результат: `import torch` из внешнего пака успешен (**SPIKE-OK**), `torch.jit.load(anime-manga-big-lama.pt)`
0.5 с, инпейнт 320×320 — 1.1 с, hole mean 208.5 (было 10). numpy 2.2.6 из бандла, torch 2.11.0+cpu из внешнего пака.

### Находка 1: frozen stdlib неполон

`import torch` упал на `ModuleNotFoundError: No module named 'timeit'` — PyInstaller включает
в `base_library.zip` только те stdlib-модули, которые нашёл анализом. torch требует и другие
модули, которых нет в графе сайдкара.

**Решение**: в базовую сборку кладётся `stdlib.zip` (весь `Lib` Python 3.10 без `test/`,
`tkinter/`, `idlelib/`, `lib2to3/`, `ensurepip/`, `site-packages/`): 703 файла, **3.0 МБ**.
При старте frozen-приложения zip добавляется в конец `sys.path`; импорт любых пропущенных
stdlib-модулей становится возможен. Проверено: после этого torch импортируется.

### Находка 2: пак — это не только `torch/`

`import torch` упал на `ModuleNotFoundError: No module named 'torchgen'` — пакет лежит
отдельным каталогом рядом с `torch/`. Значит, пак собирается как «всё, что pip поставил в чистом
venv для torch»: `torch/`, `torchgen/`, `functorch/`, `sympy/`, `networkx/`, `jinja2/`,
`markupsafe/`, `filelock/`, `fsspec/`, `mpmath/`, `typing_extensions.py`, dist-info.

### Находка 3: DLL-поиск

`os.add_dll_directory(torch/lib)` + `PATH` достаточно: `shm.dll`, `torch_cpu.dll`, `c10.dll`
загружаются из внешнего каталога. Runtime hook `pyi_rth_torch_dlls` для внешнего пака не нужен
(он про `_MEIPASS`), но остаётся безвредным; из базовой сборки его можно убрать.

## CUDA-пак

- Машина разработки: RTX 5060 Laptop (sm_120), драйвер 617.14 (KMD 617.14), CUDA UMD 13.4 → cu128 обязателен.
- Пак: `torch==2.11.0+cu128` с `https://download.pytorch.org/whl/cu128` (тот же механизм активации, DLL — в `torch/lib`).
- Проверка: `torch.cuda.is_available()`, LaMa-инференс на GPU (smoke в converge).
- Fallback: при сбое CUDA — retry на CPU (`_lama_after_failure` уже есть).

## Альтернативы

| Вариант | Плюс | Минус | Решение |
|---|---|---|---|
| CPU-torch в базе, CUDA отдельно | проще | +150 МБ к базе, ломает цель 150–200 МБ | отклонён |
| Только CUDA-пак | меньше | у Intel/AMD нет ускорения, CPU-машины обязаны качать 1.2+ ГБ | отклонён |
| Паки = wheels + pip в рантайме | меньше кода | в frozen нет pip/интерпретатора | отклонён |
| Паки = site-packages + `.7z` | нет pip, py7zr уже в базе, атомарная установка | антивирус к `.pyd` (риск) | **выбран** |

## Ссылки на код

- `src/components/lama_inpainter.py:16` — текущий `resolve_device` с frozen-shortcut.
- `src/app/model_manager.py` — образец скачивания/прогресса (`model.progress`).
- `src/app/server.py:400` — SSE `/api/events`; `AppState.fanout` — шина событий.
- `src/utils/paths.py:21` — `install_root()`, `models_dir()`; `src/app/paths.py` — portable-режим.
- `src/components/translator.py:69` — докачка языковых моделей Argos.
