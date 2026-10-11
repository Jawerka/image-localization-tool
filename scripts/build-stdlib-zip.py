"""Собрать stdlib.zip из базового Python сборки.

Frozen-интерпретатор PyInstaller несёт только те stdlib-модули, которые нашёл
анализом; torch требует и другие (`timeit` и т.п., см. specs/030
research.md). Полный stdlib кладётся в `_internal/stdlib.zip` и добавляется
в конец `sys.path` при старте (`src/app/runtime.py::_attach_stdlib`).

Запуск:
    python scripts/build-stdlib-zip.py
    python scripts/build-stdlib-zip.py --out build/runtime/stdlib.zip
"""

from __future__ import annotations

import argparse
import sys
import sysconfig
import zipfile
from pathlib import Path

DEFAULT_OUT = Path("build") / "runtime" / "stdlib.zip"
SKIP_TOP = {"test", "tkinter", "idlelib", "lib2to3", "ensurepip", "site-packages", "venv"}


def stdlib_root() -> Path:
    """Каталог исходников stdlib базового интерпретатора (не venv-надстройки)."""
    if sys.platform == "win32":
        candidate = Path(sys.base_prefix) / "Lib"
        if candidate.is_dir():
            return candidate
    return Path(sysconfig.get_paths()["stdlib"])


def build(out_path: Path, base: Path | None = None) -> tuple[int, int]:
    """Упаковать ``*.py`` из stdlib. Возвращает (файлов, байт)."""
    root = Path(base) if base is not None else stdlib_root()
    if not root.is_dir():
        raise SystemExit(f"Нет каталога stdlib: {root}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(root)
            if relative.parts[0] in SKIP_TOP:
                continue
            if "__pycache__" in relative.parts:
                continue
            archive.write(path, relative.as_posix())
            count += 1
    return count, out_path.stat().st_size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="stdlib.zip для frozen-сайдкара")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="куда положить архив")
    parser.add_argument("--base", default="", help="каталог Lib базового Python")
    args = parser.parse_args(argv)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path(__file__).resolve().parents[1] / out
    count, size = build(out, Path(args.base) if args.base else None)
    print(f"stdlib.zip: файлов {count}, {size / 1e6:.1f} МБ -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
