"""Проверка каталога onedir и чтение версии приложения.

Версия живёт только в ``src/app/__init__.py``. Её читают spec, скрипт сборки
и эта проверка. Модели сюда не копируются: их кладёт ``scripts/build-windows.ps1``
рядом с exe уже после PyInstaller.

Запуск:
    python scripts/smoke_dist.py
    python scripts/smoke_dist.py dist\\ImageLocalizationTool
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

EXE_NAME = "ImageLocalizationTool.exe"
DIST_DIR_NAME = "ImageLocalizationTool"
_FONT_SUFFIXES = {".otf", ".ttf", ".ttc"}
_SKIP_WEB_NAMES = {"mockups", "__pycache__"}
_VERSION_RE = re.compile(
    r"""^[ \t]*__version__\s*=\s*(['"])([^'"]+)\1\s*$""",
    re.MULTILINE,
)


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


def expected_font_names(root: Path | None = None) -> list[str]:
    """Имена файлов шрифтов в ``src/resources/fonts``, если каталог есть."""
    base = Path(root) if root is not None else repo_root()
    folder = base / "src" / "resources" / "fonts"
    if not folder.is_dir():
        return []
    names = [
        path.name
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in _FONT_SUFFIXES
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
    shutil.copytree(src, dest)


def dist_problems(dist: Path, source_root: Path | None = None) -> list[str]:
    """Список проблем layout. Пустой список — каталог годится."""
    root = Path(source_root) if source_root is not None else repo_root()
    dist = Path(dist)
    problems: list[str] = []
    exe = dist / EXE_NAME
    if not exe.is_file():
        problems.append(f"нет exe: {exe}")
    internal = dist / "_internal"
    if not internal.is_dir():
        problems.append(f"нет каталога _internal: {internal}")
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
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print(
            "Запуск: python scripts/smoke_dist.py [dist\\ImageLocalizationTool]",
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
    problems = dist_problems(dist)
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
