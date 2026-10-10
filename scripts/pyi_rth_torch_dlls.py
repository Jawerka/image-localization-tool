"""Runtime hook PyInstaller: каталог ``torch/lib`` в поиск DLL Windows.

Без этого spawn-воркер может не найти зависимости ``shm.dll`` / ``torch_cuda.dll``,
даже если файлы лежат в ``_internal/torch/lib``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_torch_lib() -> None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    torch_lib = Path(meipass) / "torch" / "lib"
    if not torch_lib.is_dir():
        return
    lib = str(torch_lib)
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(lib)
        except OSError:
            pass
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    if lib not in parts:
        os.environ["PATH"] = lib + (os.pathsep + path if path else "")


_add_torch_lib()
