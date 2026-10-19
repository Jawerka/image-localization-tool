"""Статические проверки сборки Windows. PyInstaller не запускается."""



from __future__ import annotations



import ast

import os

import subprocess

import sys

from pathlib import Path



from scripts.smoke_dist import (

    EXE_NAME,

    SIDECAR_DIR_NAME,

    dist_problems,

    drop_cuda_entries,

    expected_font_names,

    is_cuda_binary,

    read_app_version,

    stage_runtime_files,

    torch_lib_problems,

)



ROOT = Path(__file__).resolve().parents[2]

SPEC = ROOT / "ImageLocalizationTool.spec"

PS1 = ROOT / "scripts" / "build-windows.ps1"

ISS = ROOT / "installer" / "ImageLocalizationTool.iss"

SMOKE = ROOT / "scripts" / "smoke_dist.py"





def test_read_app_version_matches_package():

    from src.app import __version__



    assert read_app_version() == __version__


def test_portable_package_has_windows_update_contract():

    script = (ROOT / "scripts" / "package-portable.ps1").read_text(encoding="utf-8")

    assert "'components'" in script
    assert "$topLevelModels = Join-Path $stage 'models'" in script
    assert "Remove-Item -LiteralPath $topLevelModels -Recurse -Force" in script
    assert "sidecar\\_internal\\rapidocr\\models" in script
    assert "platform = 'windows-x64'" in script
    assert "host = 'desktop/ImageLocalizationTool.exe'" in script
    assert "sidecar = 'sidecar/ImageLocalizationTool.exe'" in script
    assert "web = 'web/index.html'" in script
    for name in ("update-windows.ps1", "rollback-windows.ps1", "windows-update-common.ps1"):
        assert name in script





def test_read_app_version_parses_assignment(tmp_path):

    app = tmp_path / "src" / "app"

    app.mkdir(parents=True)

    (app / "__init__.py").write_text('__version__ = "9.8.7"\n', encoding="utf-8")

    assert read_app_version(tmp_path) == "9.8.7"





def test_read_app_version_missing(tmp_path):

    app = tmp_path / "src" / "app"

    app.mkdir(parents=True)

    (app / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    try:

        read_app_version(tmp_path)

    except RuntimeError as exc:

        assert "__version__" in str(exc)

    else:

        raise AssertionError("expected RuntimeError")





def test_version_is_not_copied_into_packaging_files():

    version = read_app_version()

    for path in (SPEC, PS1, ISS, SMOKE):

        text = path.read_text(encoding="utf-8")

        assert version not in text, path.name





def test_build_script_is_ascii_and_checks_exit_codes():

    data = PS1.read_bytes()

    text = data.decode("ascii")

    assert "$ErrorActionPreference = 'Stop'" in text

    assert "$LASTEXITCODE" in text

    assert "SkipPyInstaller" in text

    assert "SkipInno" in text

    assert "SkipModels" in text

    assert "read_app_version" in text

    assert "/DAppVersion=" in text

    assert "smoke_dist.py" in text

    assert "ISCC.exe not found" in text





def test_cuda_dlls_are_dropped_and_cpu_torch_stays():

    # Весь torch/lib оставляем; чужой CUDA (onnxruntime EP, npp) — drop.

    assert not is_cuda_binary("torch/lib/torch_cuda.dll")

    assert not is_cuda_binary("torch/lib/c10_cuda.dll")

    assert not is_cuda_binary("torch/lib/cublasLt64_13.dll")

    assert not is_cuda_binary("torch/lib/cupti64_2025.3.0.dll")

    assert not is_cuda_binary("torch/lib/nvrtc64_130_0.dll")

    assert not is_cuda_binary("torch\\lib\\curand64_10.dll")

    assert not is_cuda_binary("torch/lib/torch_cpu.dll")

    assert not is_cuda_binary("torch/cuda/__init__.py")

    assert is_cuda_binary("onnxruntime_providers_cuda.dll")

    assert is_cuda_binary("nppc64_13.dll")

    assert is_cuda_binary("cublasLt64_13.dll")  # вне torch/lib

    kept = drop_cuda_entries([

        ("torch/lib/torch_cuda.dll", "src", "BINARY"),

        ("torch/lib/cublasLt64_13.dll", "src", "BINARY"),

        ("torch/lib/cupti64_2025.3.0.dll", "src", "BINARY"),

        ("cublasLt64_13.dll", "src", "BINARY"),

        ("onnxruntime_providers_cuda.dll", "src", "BINARY"),

        ("torch/lib/torch_cpu.dll", "src", "BINARY"),

        ("torch/cuda/__init__.py", "src", "DATA"),

    ])

    assert [item[0] for item in kept] == [

        "torch/lib/torch_cuda.dll",

        "torch/lib/cublasLt64_13.dll",

        "torch/lib/cupti64_2025.3.0.dll",

        "torch/lib/torch_cpu.dll",

        "torch/cuda/__init__.py",

    ]





def test_spec_has_no_torch_runtime_hook_and_keeps_cuda_drop():

    text = SPEC.read_text(encoding="utf-8")

    assert "drop_cuda_entries" in text

    assert "pyi_rth_torch_dlls" not in text

    assert "runtime_hooks=[]" in text





def test_torch_lib_problems_accepts_cpu_bundle(tmp_path):

    lib = tmp_path / SIDECAR_DIR_NAME / "_internal" / "torch" / "lib"

    lib.mkdir(parents=True)

    for name in ("shm.dll", "torch_cpu.dll", "c10.dll"):

        (lib / name).write_bytes(b"")

    assert torch_lib_problems(tmp_path) == []





def test_torch_lib_problems_requires_cuda_set_when_torch_cuda_present(tmp_path):

    lib = tmp_path / SIDECAR_DIR_NAME / "_internal" / "torch" / "lib"

    lib.mkdir(parents=True)

    for name in ("shm.dll", "torch_cpu.dll", "c10.dll", "torch_cuda.dll"):

        (lib / name).write_bytes(b"")

    assert torch_lib_problems(tmp_path), "CUDA-бандл без c10_cuda/cudart неполон"

    for name in (

        "c10_cuda.dll",

        "cudart64_130.dll",

        "cublas64_13.dll",

        "cupti64_2025.3.0.dll",

    ):

        (lib / name).write_bytes(b"")

    assert torch_lib_problems(tmp_path) == []





def test_spec_excludes_torch_and_argos_stack():

    text = SPEC.read_text(encoding="utf-8")

    tree = ast.parse(text)

    found = False

    for node in ast.walk(tree):

        if not isinstance(node, ast.keyword) or node.arg != "excludes":

            continue

        found = True

        values = ast.literal_eval(node.value)

        for name in ("torch", "torchvision", "torchgen", "functorch", "argostranslate",

                     "ctranslate2", "spacy", "sentencepiece", "sympy", "playwright"):

            assert name in values, name

    assert found





def test_spec_ships_stdlib_zip():

    text = SPEC.read_text(encoding="utf-8")

    assert "stdlib.zip" in text

    assert "stdlib_zip" in text





def test_spec_is_windowed_onedir_for_src_package():

    text = SPEC.read_text(encoding="utf-8")

    assert 'app_name = "ImageLocalizationTool"' in text

    assert 'sidecar_name = "ilt_sidecar"' in text

    assert "name=sidecar_name" in text

    assert 'project_dir / "src" / "app" / "__main__.py"' in text

    assert "pathex=[str(project_dir)]" in text

    assert "console=False" in text

    assert "exclude_binaries=True" in text

    assert 'contents_directory="_internal"' in text

    assert "read_app_version" in text

    assert "stage_runtime_files" in text

    assert "upx=False" in text

    tree = ast.parse(text)

    datas_segments = []

    for node in ast.walk(tree):

        if isinstance(node, ast.keyword) and node.arg == "datas":

            datas_segments.append(ast.get_source_segment(text, node.value) or "")

    assert datas_segments

    assert all("models" not in segment for segment in datas_segments)





def test_installer_targets_flutter_host_without_webview2():

    text = ISS.read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in text

    # Cutover: оболочка рендерится Flutter, WebView2 не нужен.

    assert "WebView2" not in text

    assert "MicrosoftEdgeWebview2Setup.exe" not in text

    assert "/DAppVersion" in text or "AppVersion" in text

    assert "#ifndef AppVersion" in text

    assert "desktop\\ImageLocalizationTool.exe" in text

    # Апгрейд поверх pywebview-раскладки: старый exe и _internal убираются.

    assert "[InstallDelete]" in text

    assert "{app}\\_internal" in text

    assert "{#DistDir}\\*" in text





def _fake_dist(tmp_path: Path) -> Path:

    """Минимальная раскладка cutover: desktop/ + sidecar/ + web/ + stdlib.zip."""

    dist = tmp_path / "ImageLocalizationTool"

    host = dist / "desktop"

    host.mkdir(parents=True)

    (host / EXE_NAME).write_bytes(b"MZ")

    (host / "flutter_windows.dll").write_bytes(b"MZ")

    (host / "data" / "flutter_assets").mkdir(parents=True)

    sidecar = dist / "sidecar"

    (sidecar / "_internal").mkdir(parents=True)

    (sidecar / EXE_NAME).write_bytes(b"MZ")

    (sidecar / "_internal" / "stdlib.zip").write_bytes(b"PK")

    return dist





def test_stage_puts_web_and_fonts_beside_exe_without_models(tmp_path):

    source = tmp_path / "srcroot"

    web = source / "web"

    (web / "css").mkdir(parents=True)

    (web / "index.html").write_text("<html></html>", encoding="utf-8")

    (web / "mockups").mkdir()

    (web / "mockups" / "index.html").write_text("mock", encoding="utf-8")

    fonts = source / "src" / "resources" / "fonts"

    fonts.mkdir(parents=True)

    (fonts / "Heroika-Regular.otf").write_bytes(b"otf")
    (fonts / "Demo.otf").write_bytes(b"extra")

    (fonts / "OFL.txt").write_text("license", encoding="utf-8")

    (source / "models").mkdir()

    (source / "models" / "big.bin").write_bytes(b"m")



    dist = _fake_dist(tmp_path)

    stage_runtime_files(dist, source)



    assert (dist / "web" / "index.html").is_file()

    assert (dist / "web" / "css").is_dir()

    assert not (dist / "web" / "mockups").exists()

    assert (dist / "fonts" / "Heroika-Regular.otf").is_file()
    assert not (dist / "fonts" / "Demo.otf").exists()

    assert (dist / "fonts" / "OFL.txt").is_file()

    assert not (dist / "models").exists()

    assert dist_problems(dist, source) == []



    (dist / "web" / "mockups").mkdir()

    problems = dist_problems(dist, source)

    assert any("mockups" in item for item in problems)





def test_dist_problems_require_shipped_fonts(tmp_path):

    names = expected_font_names()

    dist = _fake_dist(tmp_path)

    web = dist / "web"

    web.mkdir()

    (web / "index.html").write_text("<html></html>", encoding="utf-8")

    problems = dist_problems(dist)

    if names:

        assert any(name in item for name in names for item in problems)

    else:

        assert problems == []





def test_dist_problems_flags_missing_layout_parts(tmp_path):

    dist = tmp_path / "ImageLocalizationTool"

    dist.mkdir()

    problems = dist_problems(dist)

    assert any("нет хоста" in item for item in problems)

    assert any("нет сайдкара" in item for item in problems)

    assert any("нет каталога _internal" in item for item in problems)

    assert any("нет web/index.html" in item for item in problems)





def test_missing_dist_exits_2_without_traceback(tmp_path):

    missing = tmp_path / "no-such-dist"

    env = os.environ.copy()

    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(

        [sys.executable, str(SMOKE), str(missing)],

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        env=env,

        check=False,

    )

    assert result.returncode == 2

    combined = (result.stdout or "") + (result.stderr or "")

    assert "Traceback" not in combined

    assert str(missing) in combined





def test_web_root_sits_beside_install_root(tmp_path, monkeypatch):

    from src.app import server



    web = tmp_path / "web"

    web.mkdir()

    (web / "index.html").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(server, "install_root", lambda: tmp_path)

    assert server._default_web_root() == web





REQUIREMENTS_RELEASE = ROOT / "requirements-release.txt"

RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

MANIFEST = ROOT / "src" / "app" / "runtime_manifest.json"

PACK_SCRIPT = ROOT / "scripts" / "build-runtime-pack.py"

PACKS_PS1 = ROOT / "scripts" / "build-runtime-packs.ps1"

PUBLISH_PS1 = ROOT / "scripts" / "publish-release.ps1"





def test_requirements_release_has_no_heavy_stack():

    lines = [

        line.split("#", 1)[0].strip()

        for line in REQUIREMENTS_RELEASE.read_text(encoding="utf-8").splitlines()

    ]

    text = "\n".join(lines).casefold()

    for banned in ("torch", "torchvision", "argostranslate", "spacy", "ctranslate2", "playwright"):

        assert banned not in text, banned

    for needed in ("opencv-python", "rapidocr", "onnxruntime", "py7zr", "rarfile", "pyphen"):

        assert needed in text, needed





def test_runtime_manifest_schema():
    import json

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == 2
    assert data["app"] == read_app_version()
    packs = data["packs"]
    ids = {(pack["id"], pack["os"]) for pack in packs}
    assert ("torch-cpu", "win") in ids
    assert ("torch-cu128", "win") in ids
    assert ("argos", "win") in ids
    for pack in packs:
        for key in ("id", "title", "kind", "os", "python", "version", "size_bytes"):
            assert key in pack, (pack.get("id"), key)
        files = pack.get("files")
        if files:
            assert pack.get("format") == "wheels"
            total = 0
            for item in files:
                for key in ("name", "url", "sha256", "size_bytes"):
                    assert key in item, (pack["id"], key)
                assert item["url"].startswith("https://")
                assert len(item["sha256"]) == 64
                assert item["size_bytes"] > 0
                total += item["size_bytes"]
            assert pack["size_bytes"] == total
        else:
            # linux-плейсхолдеры до релизного манифеста / archive-совместимость
            assert pack["url"].startswith("https://")
    cu128 = next(pack for pack in packs if pack["id"] == "torch-cu128" and pack["os"] == "win")
    assert cu128["driver_min"] == 570
def test_smoke_flags_torch_in_release_base(tmp_path):

    dist = _fake_dist(tmp_path)

    torch_dir = dist / SIDECAR_DIR_NAME / "_internal" / "torch"

    torch_dir.mkdir()

    problems = dist_problems(dist, expect_no_torch=True)

    assert any("не должна нести torch" in item for item in problems)

    # Без флага проверяется dev-набор (каталог torch есть — проверяем lib).

    problems = dist_problems(dist)

    assert not any("не должна нести torch" in item for item in problems)





def test_smoke_requires_stdlib_zip(tmp_path):

    dist = _fake_dist(tmp_path)

    (dist / SIDECAR_DIR_NAME / "_internal" / "stdlib.zip").unlink()

    problems = dist_problems(dist)

    assert any("stdlib.zip" in item for item in problems)





def test_release_workflow_builds_and_uploads_linux_assets():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text
    assert "workflow_dispatch" in text
    assert "contents: write" in text
    assert "build-stdlib-zip.py" in text
    # Обычный релиз читает фиксированный каталог до упаковки, не разрешает зависимости.
    assert "build-runtime-manifest.py" in text
    assert "runtime-catalog.json" in text
    assert "build_runtime_locks.py" not in text
    assert "waiting for the argostranslate wheel" not in text
    assert "Frozen CPU and offline components" in text
    assert "gh release upload" in text
    assert "server-linux-x64.tar.gz" in text
    assert "packs-linux.json" in text
    assert "packs/*.7z" not in text
def test_pack_builder_skips_headers_and_tests(tmp_path):

    import importlib.util



    spec = importlib.util.spec_from_file_location("build_runtime_pack", PACK_SCRIPT)

    module = importlib.util.module_from_spec(spec)

    assert spec.loader is not None

    spec.loader.exec_module(module)



    site = tmp_path / "site-packages"

    (site / "torch" / "lib").mkdir(parents=True)

    (site / "torch" / "lib" / "shm.dll").write_bytes(b"MZ")

    (site / "torch" / "include").mkdir(parents=True)

    (site / "torch" / "include" / "header.h").write_bytes(b"#")

    (site / "torch" / "test").mkdir(parents=True)

    (site / "torch" / "test" / "test_all.py").write_text("x", encoding="utf-8")

    (site / "torch" / "__pycache__").mkdir(parents=True)

    (site / "torch" / "__pycache__" / "x.pyc").write_bytes(b"pyc")

    (site / "torch" / "stub.pyi").write_text("x", encoding="utf-8")

    (site / "torch" / "__init__.py").write_text("x = 1", encoding="utf-8")



    stage = tmp_path / "stage"

    copied = module.stage_site_packages(site, stage)

    assert copied == 2

    assert (stage / "site-packages" / "torch" / "__init__.py").is_file()

    assert (stage / "site-packages" / "torch" / "lib" / "shm.dll").is_file()

    assert not (stage / "site-packages" / "torch" / "include").exists()

    assert not (stage / "site-packages" / "torch" / "test").exists()





def test_manifest_merge_keeps_other_platform_placeholders():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_runtime_manifest", ROOT / "scripts" / "build-runtime-manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    old = [
        {"id": "torch-cpu", "os": "linux", "kind": "torch", "sha256": ""},
        {"id": "torch-cpu", "os": "win", "kind": "torch", "sha256": "old"},
    ]
    new = [{"id": "torch-cpu", "os": "win", "kind": "torch", "sha256": "new"}]
    merged = module.merge_entries(old, new)
    by_key = {(item["id"], item["os"]): item for item in merged}
    assert by_key[("torch-cpu", "win")]["sha256"] == "new"
    assert by_key[("torch-cpu", "linux")]["sha256"] == ""
    assert [item["os"] for item in merged] == ["linux", "win"]

def test_pack_script_names_and_driver_threshold():

    import importlib.util



    spec = importlib.util.spec_from_file_location("build_runtime_pack2", PACK_SCRIPT)

    module = importlib.util.module_from_spec(spec)

    assert spec.loader is not None

    spec.loader.exec_module(module)



    assert module.pack_id("torch", "cpu") == "torch-cpu"

    assert module.pack_id("torch", "cu128") == "torch-cu128"

    assert module.pack_id("argos", "") == "argos"

    assert module.DRIVER_MIN["torch-cu128"] == 570





def test_runtime_packs_and_publish_scripts_are_ascii():

    for path in (PACKS_PS1, PUBLISH_PS1, ROOT / "scripts" / "package-portable.ps1",

                 ROOT / "scripts" / "package-server.ps1"):

        data = path.read_bytes()

        text = data.decode("ascii")

        assert "$ErrorActionPreference = 'Stop'" in text

    publish = PUBLISH_PS1.read_bytes().decode("ascii")

    assert "publish" in publish

    assert "SHA256SUMS" in publish

    assert "--clobber" in publish

