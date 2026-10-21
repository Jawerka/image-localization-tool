"""Проверка раскладки dist и чтение версии приложения.

Раскладка cutover: ``desktop/`` — Flutter-хост, ``sidecar/`` — PyInstaller
(``_internal``), ``web/`` и ``fonts/`` — в корне, ``models/`` — по опции.
Версия живёт только в ``src/app/__init__.py``. Модели кладёт
``scripts/build-windows.ps1`` в корень раскладки уже после сборки.

Релизная база не должна нести torch: ``--expect-no-torch`` валит
сборку, если каталог ``torch`` попал в ``_internal``. ``stdlib.zip`` в
``_internal`` обязателен для любого onedir: внешний torch-пак требует
полный stdlib (см. specs/030-runtime-deployment/research.md).

Запуск:
    python scripts/smoke_dist.py
    python scripts/smoke_dist.py dist\\ImageLocalizationTool --expect-no-torch
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

EXE_NAME = "ImageLocalizationTool.exe"
DIST_DIR_NAME = "ImageLocalizationTool"
HOST_DIR_NAME = "desktop"
SIDECAR_DIR_NAME = "sidecar"
_FONT_SUFFIXES = {".otf", ".ttf", ".ttc"}
_SKIP_WEB_NAMES = {"mockups", "__pycache__"}
_VERSION_RE = re.compile(
    r"""^[ \t]*__version__\s*=\s*(['"])([^'"]+)\1\s*$""",
    re.MULTILINE,
)
# Чужой CUDA-стек (onnxruntime EP, npp* и т.п.). Всё из torch/lib не трогаем:
# иначе WinError 126 на shm.dll (не хватает зависимостей torch_cuda / torch_cpu).
_CUDA_MARKERS = (
    "cuda",
    "cublas",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "nvrtc",
    "nvjitlink",
    "cupti",
    "nvjpeg",
    "nppc",
    "nppi",
    "npps",
)
_BINARY_SUFFIXES = (".dll", ".so", ".dylib", ".pyd")
_TORCH_LIB_MARKERS = ("torch/lib/", "torch\\lib\\", "/torch/lib", "\\torch\\lib")
# Минимальный набор в onedir для import torch + LaMa. CPU-сборка (релиз) несёт
# только это; CUDA-набор проверяем ниже, когда torch_cuda.dll реально в бандле.
_REQUIRED_TORCH_DLL_GLOBS = (
    "shm.dll",
    "torch_cpu.dll",
    "c10.dll",
)
# Дополнительно для CUDA-сборки (dev-машина с GPU).
_REQUIRED_TORCH_CUDA_DLL_GLOBS = (
    "torch_cuda.dll",
    "c10_cuda.dll",
    "cudart64_*.dll",
    "cublas64_*.dll",
    "cupti64_*.dll",
)


def _is_torch_lib_path(path: str) -> bool:
    """Путь внутри каталога библиотек PyTorch — никогда не выкидываем."""
    normalized = str(path).replace("\\", "/").casefold()
    return "/torch/lib/" in f"/{normalized}/" or normalized.endswith("/torch/lib")


def is_cuda_binary(path: str) -> bool:
    """DLL CUDA вне ``torch/lib``. Файлы PyTorch всегда остаются в сборке."""
    text = str(path)
    if _is_torch_lib_path(text):
        return False
    name = Path(text).name.casefold()
    if not name.endswith(_BINARY_SUFFIXES):
        return False
    return any(marker in name for marker in _CUDA_MARKERS)


def drop_cuda_entries(entries):
    """Убрать из списка PyInstaller чужие CUDA DLL; ``torch/lib`` не трогать."""
    kept = []
    for entry in entries:
        name = entry[0] if isinstance(entry, (tuple, list)) and entry else entry
        if is_cuda_binary(str(name)):
            continue
        kept.append(entry)
    return kept


def torch_lib_problems(dist: Path) -> list[str]:
    """Проверка обязательных DLL PyTorch в сайдкаре.

    CPU-сборке (релиз) хватает CPU-набора; CUDA-набор требуется, только если
    ``torch_cuda.dll`` реально попал в бандл (сборка с dev-venv на GPU).
    """
    lib = Path(dist) / SIDECAR_DIR_NAME / "_internal" / "torch" / "lib"
    if not lib.is_dir():
        return [f"нет каталога torch/lib: {lib}"]
    required = list(_REQUIRED_TORCH_DLL_GLOBS)
    if (lib / "torch_cuda.dll").is_file():
        required.extend(_REQUIRED_TORCH_CUDA_DLL_GLOBS)
    problems: list[str] = []
    for pattern in required:
        if "*" in pattern:
            if not any(lib.glob(pattern)):
                problems.append(f"нет {pattern} в {lib}")
        elif not (lib / pattern).is_file():
            problems.append(f"нет {lib / pattern}")
    return problems


def repo_root() -> Path:
    """Корень репозитория: родитель каталога ``scripts``."""
    return Path(__file__).resolve().parents[1]


def read_app_version(root: Path | None = None) -> str:
    """Прочитать ``__version__`` из ``src/app/__init__.py``."""
    base = Path(root) if root is not None else repo_root()
    path = base / "src" / "app" / "__init__.py"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RuntimeError(f"Не удалось прочитать версию: {path}") from exc
    match = _VERSION_RE.search(text)
    if not match:
        raise RuntimeError(f"В {path} нет строки __version__")
    return match.group(2)


_REQUIRED_BASE_FONTS = (
    "Heroika-Regular.otf",
    "Jupiteroid-Light.ttf",
)


def expected_font_names(root: Path | None = None) -> list[str]:
    """Имена файлов шрифтов в ``src/resources/fonts``, которые едут в базе."""
    base = Path(root) if root is not None else repo_root()
    folder = base / "src" / "resources" / "fonts"
    if not folder.is_dir():
        return []
    names = [
        path.name
        for path in folder.iterdir()
        if path.is_file() and path.name in _REQUIRED_BASE_FONTS
    ]
    names.sort()
    return names


def _ignore_web(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if name.casefold() in _SKIP_WEB_NAMES]


def stage_runtime_files(dist: Path, source_root: Path | None = None) -> None:
    """Положить ``web`` (без mockups) и шрифты в корень onedir.

    Шрифты оказываются в ``fonts/`` рядом с exe: оттуда их берёт ``resolve_font``.
    Каталог ``models`` эта функция не трогает.
    """
    root = Path(source_root) if source_root is not None else repo_root()
    dist = Path(dist)
    if not dist.is_dir():
        raise RuntimeError(f"Каталог сборки не найден: {dist}")
    _stage_web(root / "web", dist / "web")
    _stage_fonts(root / "src" / "resources" / "fonts", dist / "fonts")


def _stage_web(src: Path, dest: Path) -> None:
    if not (src / "index.html").is_file():
        raise RuntimeError(f"Нет web/index.html: {src / 'index.html'}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=_ignore_web)
    leaked = [path for path in dest.rglob("*") if path.name.casefold() == "mockups"]
    if leaked:
        raise RuntimeError(f"В сборку попал каталог mockups: {leaked[0]}")


def _stage_fonts(src: Path, dest: Path) -> None:
    if not src.is_dir():
        return
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in (*_REQUIRED_BASE_FONTS, "OFL.txt", "CC0.txt"):
        path = src / name
        if path.is_file():
            shutil.copy2(path, dest / name)


def dist_problems(
    dist: Path,
    source_root: Path | None = None,
    *,
    expect_no_torch: bool = False,
) -> list[str]:
    """Список проблем layout. Пустой список — каталог годится."""
    root = Path(source_root) if source_root is not None else repo_root()
    dist = Path(dist)
    problems: list[str] = []
    host_dir = dist / HOST_DIR_NAME
    host_exe = host_dir / EXE_NAME
    if not host_exe.is_file():
        problems.append(f"нет хоста: {host_exe}")
    if not (host_dir / "flutter_windows.dll").is_file():
        problems.append(f"нет рантайма Flutter: {host_dir / 'flutter_windows.dll'}")
    if not (host_dir / "data" / "flutter_assets").is_dir():
        problems.append(f"нет ассетов Flutter: {host_dir / 'data' / 'flutter_assets'}")
    sidecar_exe = dist / SIDECAR_DIR_NAME / EXE_NAME
    if not sidecar_exe.is_file():
        problems.append(f"нет сайдкара: {sidecar_exe}")
    internal = dist / SIDECAR_DIR_NAME / "_internal"
    if not internal.is_dir():
        problems.append(f"нет каталога _internal: {internal}")
    elif not (internal / "stdlib.zip").is_file():
        problems.append(f"нет stdlib.zip (frozen stdlib неполон): {internal / 'stdlib.zip'}")
    index = dist / "web" / "index.html"
    if not index.is_file():
        problems.append(f"нет web/index.html: {index}")
    web = dist / "web"
    if web.is_dir():
        leaked = [path for path in web.rglob("*") if path.name.casefold() == "mockups"]
        if leaked:
            problems.append(f"в сборке не должно быть web/mockups: {leaked[0]}")
    for name in expected_font_names(root):
        font = dist / "fonts" / name
        if not font.is_file():
            problems.append(f"нет шрифта: {font}")
    if (internal / "torch").is_dir():
        if expect_no_torch:
            problems.append(
                f"релизная база не должна нести torch: {internal / 'torch'}"
            )
        else:
            # Dev-сборка с torch: минимальный CPU-набор обязателен.
            problems.extend(torch_lib_problems(dist))
    if expect_no_torch:
        for name in ("argostranslate", "ctranslate2", "sentencepiece"):
            if (internal / name).exists():
                problems.append(f"В базу попал скачиваемый компонент: {name}")
        for path in (internal / "rapidocr").rglob("*.onnx"):
            problems.append(f"В базу попала скачиваемая OCR-модель: {path.name}")
        if any(p.is_file() and p.name not in _REQUIRED_BASE_FONTS and p.suffix in _FONT_SUFFIXES
               for p in (dist / "fonts").glob("*")):
            problems.append("В базу попали дополнительные скачиваемые шрифты")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    expect_no_torch = "--expect-no-torch" in args
    args = [item for item in args if item != "--expect-no-torch"]
    if len(args) > 1:
        print(
            "Запуск: python scripts/smoke_dist.py [dist\\ImageLocalizationTool] [--expect-no-torch]",
            file=sys.stderr,
        )
        return 2
    dist = Path(args[0]) if args else repo_root() / "dist" / DIST_DIR_NAME
    if not dist.is_absolute():
        dist = Path.cwd() / dist
    if not dist.is_dir():
        print(f"Каталог сборки не найден: {dist}", file=sys.stderr)
        print(
            "Onedir ещё не собран. Сборка: scripts\\build-windows.ps1",
            file=sys.stderr,
        )
        return 2
    problems = dist_problems(dist, expect_no_torch=expect_no_torch)
    if problems:
        print(f"Сборка не прошла проверку: {dist}", file=sys.stderr)
        for item in problems:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(f"Dist OK: {dist}")
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception as exc:
        print(f"Проверка сборки не выполнилась: {exc}", file=sys.stderr)
        status = 1
    raise SystemExit(status)
