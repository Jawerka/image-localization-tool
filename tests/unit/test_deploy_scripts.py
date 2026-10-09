"""Статические проверки скриптов деплоя. SSH и robocopy не вызываются."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "scripts" / "deploy-windows.ps1"
LAN = ROOT / "scripts" / "deploy-lan.ps1"
EXT = ROOT / "scripts" / "deploy-extension.ps1"
INNO = ROOT / "scripts" / "check-inno.ps1"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_deploy_windows_script_is_ascii_and_skips_models_by_default():
    data = WIN.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "IncludeModels" in text
    assert "SkipInno" in text
    assert "-Build" in text or "$Build" in text
    assert "robocopy" in text
    assert "models" in text
    assert "ImageLocalizationTool.exe" in text
    assert r"D:\Documents\apps\ImageLocalizationTool" in text or "apps\\ImageLocalizationTool" in text


def test_deploy_lan_script_has_host_fallback_and_preserves_runtime():
    data = LAN.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "192.168.88.41" in text
    assert "192.168.88.168" in text
    assert "DryRun" in text
    assert "ilt.service" in text
    assert "/opt/image-localization-tool" in text
    assert "venv" in text or "models" in text or "config" in text
    assert "systemctl restart" in text


def test_ci_workflow_runs_filtered_unit_tests():
    text = CI.read_text(encoding="utf-8")
    assert "pytest tests/unit" in text
    assert "not slow" in text
    assert "not ui" in text
    assert "not requires_llm" in text
    assert "not requires_argos" in text
    assert "pull_request" in text
    assert "npm run test:js" in text
    assert "Frontend unit tests" in text


def test_deploy_extension_script_builds_and_mirrors():
    data = EXT.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "build-extension.py" in text
    assert "dist\\chromium" in text or "dist/chromium" in text
    assert "apps\\extension\\image-localization-tool" in text
    assert "robocopy" in text
    assert "SkipBuild" in text


def test_check_inno_script_reports_or_installs():
    data = INNO.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "ISCC.exe" in text
    assert "SkipInno" in text
    assert "winget" in text
    assert "JRSoftware.InnoSetup" in text
