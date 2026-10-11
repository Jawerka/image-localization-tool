# -*- mode: python ; coding: utf-8 -*-
# ruff: noqa: E402, F821
"""
PyInstaller onedir для Image Localization Tool.

Запуск (его выполняет scripts/build-windows.ps1):
    venv\\Scripts\\python.exe -m PyInstaller ImageLocalizationTool.spec --clean --noconfirm

Результат: dist/ilt_sidecar/ImageLocalizationTool.exe (сайдкар раскладки cutover).
Рядом с exe, не в _internal: web/ без mockups и fonts/ (промежуточно; сборка
укладывает их в корень dist/ImageLocalizationTool).
Каталог models/ сюда не входит. Его копирует scripts/build-windows.ps1
в корень dist/ImageLocalizationTool/models уже после сборки.

База релиза — без torch и Argos-стека: они ставятся отдельными паками
(specs/030-runtime-deployment, src/app/runtime.py). torch/Argos/спутники
исключены, чтобы onedir не распух и не тянул CUDA. Вместе с базой кладётся
stdlib.zip (scripts/build-stdlib-zip.py): frozen stdlib неполон, а внешнему
torch нужны модули вроде timeit.

Нужен PyInstaller 6: собранные библиотеки лежат в _internal.
"""

import importlib.util
import sys
from pathlib import Path

project_dir = Path(SPEC).parent.resolve() if "SPEC" in globals() else Path.cwd().resolve()
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

from scripts.smoke_dist import drop_cuda_entries, read_app_version, stage_runtime_files

# Разбор page_pipeline тянет torch и легко упирается в лимит рекурсии.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))

app_name = "ImageLocalizationTool"
# Имя каталога PyInstaller-сборки: сборка укладывает его в sidecar/ рядом
# с Flutter-хостом (desktop/), чтобы one-dir бандлы не пересекались.
sidecar_name = "ilt_sidecar"
app_version = read_app_version(project_dir)

# Модели RapidOCR лежат внутри установленного пакета, не в каталоге models/:
# site-packages/rapidocr/models/*.onnx, а также config.yaml и default_models.yaml.
# Если пакет не импортируется, datas остаются пустыми и spec не падает.
rapidocr_datas = []
rapidocr_hidden = []
try:
    import rapidocr
except Exception:
    rapidocr = None
else:
    rapidocr_hidden.append(rapidocr.__name__)
    try:
        from PyInstaller.utils.hooks import collect_data_files, collect_submodules
    except Exception:
        collect_data_files = None
        collect_submodules = None
    if collect_data_files is not None:
        try:
            rapidocr_datas = collect_data_files("rapidocr")
        except Exception:
            rapidocr_datas = []
    if collect_submodules is not None:
        try:
            found = collect_submodules("rapidocr")
        except Exception:
            found = []
        if found:
            rapidocr_hidden = found

webview_hidden = []
for _mod_name in (
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
):
    if importlib.util.find_spec(_mod_name) is not None:
        webview_hidden.append(_mod_name)

# stdlib.zip готовит scripts/build-windows.ps1 до запуска spec. Без него
# сборка не падает (dev), но релизная база обязана нести архив: smoke ловит.
stdlib_zip = project_dir / "build" / "runtime" / "stdlib.zip"
datas = [*rapidocr_datas]
if stdlib_zip.is_file():
    datas.append((str(stdlib_zip), "."))
else:
    print(f"WARNING: нет {stdlib_zip}; stdlib.zip не попадёт в _internal")
# Встроенный манифест рантайма: список паков и sha256 для офлайн-установки.
datas.append((str(project_dir / "src" / "app" / "runtime_manifest.json"), "src/app"))


def _file_version_tuple(version: str) -> tuple:
    numbers = []
    for piece in version.split("."):
        digits = []
        for char in piece:
            if not char.isdigit():
                break
            digits.append(char)
        numbers.append(int("".join(digits)) if digits else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers[:4])


def _version_info_text(version: str) -> str:
    major, minor, micro, extra = _file_version_tuple(version)
    safe = version.replace("\\", "").replace('"', "")
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {micro}, {extra}),
    prodvers=({major}, {minor}, {micro}, {extra}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Image Localization Tool'),
        StringStruct('FileDescription', 'Image Localization Tool'),
        StringStruct('FileVersion', '{safe}'),
        StringStruct('InternalName', 'ImageLocalizationTool'),
        StringStruct('OriginalFilename', 'ImageLocalizationTool.exe'),
        StringStruct('ProductName', 'Image Localization Tool'),
        StringStruct('ProductVersion', '{safe}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


# PyInstaller 6.22 отдаёт путь сборки как workpath (раньше WORKPATH).
_version_file = Path(workpath) / "ImageLocalizationTool-version.txt"
_version_file.parent.mkdir(parents=True, exist_ok=True)
_version_file.write_text(_version_info_text(app_version), encoding="utf-8")

# pathex — корень репозитория. Иначе точка входа src/app/__main__.py
# не находит пакет src: каталог скрипта на sys.path указывает на src/app.
a = Analysis(
    [str(project_dir / "src" / "app" / "__main__.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "src",
        "src.app",
        "src.app.runtime",
        "src.app.hardware",
        "src.app.deploy",
        "src.page_pipeline",
        "rarfile",
        "py7zr",
        *rapidocr_hidden,
        *webview_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Тяжёлые рантаймы — внешние паки (specs/030): в базе их нет.
        "torch",
        "torchvision",
        "torchgen",
        "functorch",
        "argostranslate",
        "ctranslate2",
        "spacy",
        "stanza",
        "sentencepiece",
        "sacremoses",
        "minisbd",
        "sympy",
        "networkx",
        "jinja2",
        "mpmath",
        "scipy",
        "matplotlib",
        # Dev-инструменты.
        "playwright",
        "pytest",
        "black",
        "ruff",
        "IPython",
        "jupyter",
        "notebook",
        "sphinx",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

# Базы torch не касается (его нет). Режем чужой CUDA: onnxruntime EP, npp* и т.п.
a.binaries = drop_cuda_entries(a.binaries)
a.datas = drop_cuda_entries(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    contents_directory="_internal",
    version=str(_version_file),
)


class _StagedCollect(COLLECT):
    """После сборки кладёт web и шрифты рядом с exe, не в _internal.

    Каталог промежуточный: scripts/build-windows.ps1 переносит exe и _internal
    в `dist/ImageLocalizationTool/sidecar`, а web и fonts — в корень раскладки.
    """

    def assemble(self):
        super().assemble()
        dist_root = Path(DISTPATH) / sidecar_name
        exe_path = dist_root / f"{app_name}.exe"
        if not exe_path.is_file():
            raise RuntimeError(f"Onedir exe is missing after COLLECT: {exe_path}")
        stage_runtime_files(dist_root, project_dir)


coll = _StagedCollect(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=sidecar_name,
)
if coll is None:
    raise RuntimeError("COLLECT was not created")
