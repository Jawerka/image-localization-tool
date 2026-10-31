"""Статические проверки скриптов деплоя. SSH и robocopy не вызываются."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "scripts" / "deploy-windows.ps1"
LAN = ROOT / "scripts" / "deploy-lan.ps1"
EXT = ROOT / "scripts" / "deploy-extension.ps1"
SPEC = ROOT / "ImageLocalizationTool.spec"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_deploy_windows_script_is_ascii_and_skips_models_by_default():
    data = WIN.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "IncludeModels" in text
    assert "SkipInno" not in text
    assert "-Build" in text or "$Build" in text
    assert "robocopy" in text
    assert "models" in text
    assert "data" in text
    assert "ImageLocalizationTool.exe" in text
    assert r"D:\Documents\apps\ImageLocalizationTool" in text or "apps\\ImageLocalizationTool" in text


def test_deploy_lan_script_uses_current_host_and_proxy_jump():
    data = LAN.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "192.168.88.41" in text
    assert '[string[]] $Hosts = @("192.168.88.41")' in text
    assert '[string] $ProxyJump = "pve.30"' in text
    assert "'-J', $ProxyJump" in text
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


def test_update_probe_keeps_temp_data_in_app():
    text = (ROOT / "scripts" / "windows-update-common.ps1").read_text(encoding="utf-8")
    assert "ILT_SKIP_KEYRING_MIGRATION" not in text
    assert "data\\tmp" in text
    assert "ilt-probe-" in text


def test_spec_excludes_pywebview():
    text = SPEC.read_text(encoding="utf-8")
    assert '"webview"' in text
    assert "webview_hidden" not in text
    assert "def _has_module(" not in text


def test_spec_checks_the_built_exe_by_platform():
    text = SPEC.read_text(encoding="utf-8")
    # на Linux бинарник без .exe: COLLECT-проверка не должна требовать суффикс
    assert 'exe_name = f"{app_name}.exe" if sys.platform == "win32" else app_name' in text
    assert 'exe_path = dist_root / f"{app_name}.exe"' not in text


def test_runtime_manifest_cli_merges_two_pack_summaries(tmp_path):
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "build_runtime_manifest", ROOT / "scripts" / "build-runtime-manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    win = tmp_path / "packs.json"
    win.write_text(
        json.dumps(
            [
                {
                    "id": "torch-cpu",
                    "kind": "torch",
                    "os": "win",
                    "version": "2.11.0+cpu",
                    "python": "310",
                    "format": "wheels",
                    "size_bytes": 1,
                    "files": [{
                        "name": "torch.whl",
                        "url": "https://example.invalid/torch.whl",
                        "sha256": "a" * 64,
                        "size_bytes": 1,
                    }],
                }
            ]
        ),
        encoding="utf-8",
    )
    linux = tmp_path / "packs-linux.json"
    # BOM не должен ронять чтение сводки
    linux.write_text(
        json.dumps(
            [
                {
                    "id": "argos",
                    "kind": "argos",
                    "os": "linux",
                    "version": "1.11.1",
                    "python": "310",
                    "format": "wheels",
                    "size_bytes": 2,
                    "files": [{
                        "name": "argos.whl",
                        "url": "https://example.invalid/argos.whl",
                        "sha256": "b" * 64,
                        "size_bytes": 2,
                    }],
                }
            ]
        ),
        encoding="utf-8-sig",
    )
    out = tmp_path / "manifest.json"

    status = module.main(
        [
            "--packs",
            str(win),
            "--packs",
            str(linux),
            "--out",
            str(out),
            "--no-bundled",
        ]
    )

    assert status == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    keys = sorted((item["id"], item["os"]) for item in manifest["packs"])
    assert keys == [("argos", "linux"), ("torch-cpu", "win")]
