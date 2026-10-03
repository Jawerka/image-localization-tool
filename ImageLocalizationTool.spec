# -*- mode: python ; coding: utf-8 -*-
# ruff: noqa: E402, F821
"""
PyInstaller onedir для Image Localization Tool.

Запуск (его выполняет scripts/build-windows.ps1):
    venv\\Scripts\\python.exe -m PyInstaller ImageLocalizationTool.spec --clean --noconfirm

Результат: dist/ImageLocalizationTool/ImageLocalizationTool.exe
Рядом с exe, не в _internal: web/ без mockups и fonts/.
Каталог models/ сюда не входит. Его копирует scripts/build-windows.ps1
в dist/ImageLocalizationTool/models уже после сборки.

Нужен PyInstaller 6: собранные библиотеки лежат в _internal.
torch не исключать: LaMa и Argos (stanza) без него не работают.
"""

import importlib.util
import sys
from pathlib import Path

project_dir = Path(SPEC).parent.resolve() if "SPEC" in globals() else Path.cwd().resolve()
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

from scripts.smoke_dist import read_app_version, stage_runtime_files

# Разбор page_pipeline тянет torch и легко упирается в лимит рекурсии.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))

app_name = "ImageLocalizationTool"
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


_version_file = Path(WORKPATH) / "ImageLocalizationTool-version.txt"
_version_file.parent.mkdir(parents=True, exist_ok=True)
_version_file.write_text(_version_info_text(app_version), encoding="utf-8")

# pathex — корень репозитория. Иначе точка входа src/app/__main__.py
# не находит пакет src: каталог скрипта на sys.path указывает на src/app.
a = Analysis(
    [str(project_dir / "src" / "app" / "__main__.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[*rapidocr_datas],
    hiddenimports=[
        "src",
        "src.app",
        "src.page_pipeline",
        *rapidocr_hidden,
        *webview_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "sphinx",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

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
    """После сборки кладёт web и шрифты рядом с exe, не в _internal."""

    def assemble(self):
        super().assemble()
        dist_root = Path(DISTPATH) / app_name
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
    name=app_name,
)
if coll is None:
    raise RuntimeError("COLLECT was not created")
