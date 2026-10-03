"""Статические проверки сборки Windows. PyInstaller не запускается."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from scripts.smoke_dist import (
    dist_problems,
    expected_font_names,
    read_app_version,
    stage_runtime_files,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "ImageLocalizationTool.spec"
PS1 = ROOT / "scripts" / "build-windows.ps1"
ISS = ROOT / "installer" / "ImageLocalizationTool.iss"
SMOKE = ROOT / "scripts" / "smoke_dist.py"


def test_read_app_version_matches_package():
    from src.app import __version__

    assert read_app_version() == __version__


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
    assert "read_app_version" in text
    assert "/DAppVersion=" in text
    assert "smoke_dist.py" in text
    assert "ISCC.exe not found" in text


def test_spec_does_not_exclude_torch():
    text = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "excludes":
            continue
        found = True
        segment = ast.get_source_segment(text, node.value) or ""
        assert "torch" not in segment
        values = ast.literal_eval(node.value)
        assert "torch" not in values
        assert not any(str(item).startswith("torch.") for item in values)
    assert found


def test_spec_is_windowed_onedir_for_src_package():
    text = SPEC.read_text(encoding="utf-8")
    assert 'app_name = "ImageLocalizationTool"' in text
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


def test_installer_is_per_user_and_installs_webview2():
    text = ISS.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "WebView2" in text
    assert "MicrosoftEdgeWebview2Setup.exe" in text
    assert "/DAppVersion" in text or "AppVersion" in text
    assert "#ifndef AppVersion" in text
    assert "ImageLocalizationTool.exe" in text
    assert "{#DistDir}\\*" in text


def test_stage_puts_web_and_fonts_beside_exe_without_models(tmp_path):
    source = tmp_path / "srcroot"
    web = source / "web"
    (web / "css").mkdir(parents=True)
    (web / "index.html").write_text("<html></html>", encoding="utf-8")
    (web / "mockups").mkdir()
    (web / "mockups" / "index.html").write_text("mock", encoding="utf-8")
    fonts = source / "src" / "resources" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "Demo.otf").write_bytes(b"otf")
    (fonts / "OFL.txt").write_text("license", encoding="utf-8")
    (source / "models").mkdir()
    (source / "models" / "big.bin").write_bytes(b"m")

    dist = tmp_path / "ImageLocalizationTool"
    dist.mkdir()
    (dist / "_internal").mkdir()
    (dist / "ImageLocalizationTool.exe").write_bytes(b"MZ")
    stage_runtime_files(dist, source)

    assert (dist / "web" / "index.html").is_file()
    assert (dist / "web" / "css").is_dir()
    assert not (dist / "web" / "mockups").exists()
    assert (dist / "fonts" / "Demo.otf").is_file()
    assert (dist / "fonts" / "OFL.txt").is_file()
    assert not (dist / "models").exists()
    assert dist_problems(dist, source) == []

    (dist / "web" / "mockups").mkdir()
    problems = dist_problems(dist, source)
    assert any("mockups" in item for item in problems)


def test_dist_problems_require_shipped_fonts(tmp_path):
    names = expected_font_names()
    dist = tmp_path / "ImageLocalizationTool"
    (dist / "_internal").mkdir(parents=True)
    (dist / "ImageLocalizationTool.exe").write_bytes(b"MZ")
    web = dist / "web"
    web.mkdir()
    (web / "index.html").write_text("<html></html>", encoding="utf-8")
    problems = dist_problems(dist)
    if names:
        assert any(name in item for name in names for item in problems)
    else:
        assert problems == []


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
