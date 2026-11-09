"""Статические проверки скриптов деплоя. SSH и robocopy не вызываются."""

from __future__ import annotations

from pathlib import Path

import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "scripts" / "deploy-windows.ps1"
LAN = ROOT / "scripts" / "deploy-lan.ps1"
EXT = ROOT / "scripts" / "deploy-extension.ps1"
SPEC = ROOT / "ImageLocalizationTool.spec"
CI = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.mark.skipif(os.name != "nt", reason="Проверяется реальный robocopy Windows")
@pytest.mark.parametrize("include_models", [False, True])
def test_deploy_preserves_files_when_bundle_contains_persistent_placeholders(tmp_path, include_models):
    """Пустые каталоги portable не должны очищать пользовательскую установку."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "deploy-windows.ps1"
    script.write_bytes(WIN.read_bytes())
    source = tmp_path / "dist" / "ImageLocalizationTool"
    target = tmp_path / "apps" / "ImageLocalizationTool"
    assert source.resolve().is_relative_to(tmp_path.resolve())
    assert target.resolve().is_relative_to(tmp_path.resolve())
    for path in ["desktop/ImageLocalizationTool.exe", "sidecar/ImageLocalizationTool.exe", "web/index.html"]:
        staged = source / path
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("new-code", encoding="utf-8")
    folders = ["data", "models", "runtime", ".resources", ".downloads", ".builtin", "components"]
    for name in folders:
        (source / name).mkdir()
        (source / name / ".keep").touch()
        saved = target / name / "nested" / "saved.bin"
        saved.parent.mkdir(parents=True)
        saved.write_bytes(b"user-data-must-survive")
    (target / 'personal-notes.txt').write_bytes(b'keep root files')
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Dest", str(target)]
    if include_models:
        command.append("-IncludeModels")
    result = subprocess.run(command, capture_output=True, timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")
    for name in folders:
        assert (target / name / "nested" / "saved.bin").read_bytes() == b"user-data-must-survive"
    assert (target / 'personal-notes.txt').read_bytes() == b'keep root files'
    backups = list(target.parent.glob('.ImageLocalizationTool.backup'))
    assert len(backups) == 1
    assert not list(target.parent.glob('.ImageLocalizationTool.backup-*'))
    assert not list(target.parent.glob('.ImageLocalizationTool.backup.staging'))
    assert (backups[0]/'data/nested/saved.bin').read_bytes() == b'user-data-must-survive'
    assert (target / "web" / "index.html").read_text(encoding="utf-8") == "new-code"


@pytest.mark.skipif(os.name != 'nt', reason='Проверяется реальный robocopy Windows')
def test_windows_dry_run_does_not_create_target_or_backup(tmp_path):
    """Dry run читает артефакты, но не создаёт установку или резервные папки."""
    scripts = tmp_path/'scripts'
    scripts.mkdir()
    script = scripts/'deploy-windows.ps1'
    script.write_bytes(WIN.read_bytes())
    source = tmp_path/'dist/ImageLocalizationTool'
    for rel in ['desktop/ImageLocalizationTool.exe', 'sidecar/ImageLocalizationTool.exe', 'web/index.html']:
        file = source/rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'new code')
    target = tmp_path/'new-install'
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                             '-Dest', str(target), '-DryRun'], capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert not target.exists()
    assert not list(tmp_path.glob('.*.backup'))
    assert not list(tmp_path.glob('.*.backup-*'))
    assert not list(tmp_path.glob('.*.backup.staging'))


@pytest.mark.skipif(os.name != 'nt', reason='Проверяется PowerShell Windows')
@pytest.mark.skipif(os.name != "nt", reason="Проверяется реальный robocopy Windows")
def test_windows_second_deploy_replaces_single_backup(tmp_path):
    """Повторный деплой перезаписывает одну .backup и не оставляет GUID-копии."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy-windows.ps1").write_bytes(WIN.read_bytes())
    source = tmp_path / "dist" / "ImageLocalizationTool"
    target = tmp_path / "apps" / "ImageLocalizationTool"
    for rel in ["desktop/ImageLocalizationTool.exe", "sidecar/ImageLocalizationTool.exe", "web/index.html"]:
        staged = source / rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("first-code", encoding="utf-8")
    data = target / "data" / "project.json"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"user project")
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "deploy-windows.ps1"), "-Dest", str(target)]
    first = subprocess.run(command, capture_output=True, timeout=60)
    assert first.returncode == 0, (first.stdout + first.stderr).decode(errors="replace")
    (source / "web" / "index.html").write_text("second-code", encoding="utf-8")
    leftover = target.parent / ".ImageLocalizationTool.backup-deadbeef"
    leftover.mkdir()
    (leftover / "stale.txt").write_text("old", encoding="utf-8")
    second = subprocess.run(command, capture_output=True, timeout=60)
    assert second.returncode == 0, (second.stdout + second.stderr).decode(errors="replace")
    backups = list(target.parent.glob(".ImageLocalizationTool.backup"))
    assert len(backups) == 1
    assert not list(target.parent.glob(".ImageLocalizationTool.backup-*"))
    assert not leftover.exists()
    assert (backups[0] / "web" / "index.html").read_text(encoding="utf-8") == "first-code"
    assert (target / "web" / "index.html").read_text(encoding="utf-8") == "second-code"
    assert data.read_bytes() == b"user project"


def test_windows_incomplete_backup_blocks_code_changes_even_with_zero_exit_code(tmp_path):
    """Ложный успех копирования не должен разрешать запись поверх установки."""
    scripts = tmp_path/'scripts'
    scripts.mkdir()
    (scripts/'deploy-windows.ps1').write_bytes(WIN.read_bytes())
    source = tmp_path/'dist/ImageLocalizationTool'
    target = tmp_path/'apps/ImageLocalizationTool'
    for rel in ['desktop/ImageLocalizationTool.exe', 'sidecar/ImageLocalizationTool.exe', 'web/index.html']:
        for directory, content in [(source, b'new code'), (target, b'old code')]:
            file = directory/rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
    data = target/'data/project.json'
    data.parent.mkdir()
    data.write_bytes(b'user project')
    wrapper = tmp_path/'fixture.ps1'
    wrapper.write_text("function global:robocopy { $global:LASTEXITCODE = 0 }\n"
                       "& (Join-Path $PSScriptRoot 'scripts/deploy-windows.ps1') "
                       "-Dest (Join-Path $PSScriptRoot 'apps/ImageLocalizationTool')\n", encoding='ascii')
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)],
                            capture_output=True, timeout=60)
    assert result.returncode != 0
    assert b'Backup file missing' in result.stderr
    assert (target/'web/index.html').read_bytes() == b'old code'
    assert data.read_bytes() == b'user project'


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
    assert ".backup" in text
    assert "NewGuid" not in text
    assert "ImageLocalizationTool.exe" in text
    assert r"D:\Documents\apps\ImageLocalizationTool" in text or "apps\\ImageLocalizationTool" in text


def test_deploy_lan_script_uses_current_host_and_proxy_jump():
    data = LAN.read_bytes()
    text = data.decode("ascii")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "192.168.88.41" in text
    assert '[string[]] $Hosts = @("192.168.88.41")' in text
    assert '[string] $ProxyJump = "pve.30"' in text
    driver = (ROOT / 'scripts/lan_deploy.py').read_text(encoding='utf-8')
    remote = (ROOT / 'scripts/lan_deploy_remote.py').read_text(encoding='utf-8')
    assert "'-J', args.proxy_jump" in driver
    assert "DryRun" in text
    assert "ilt.service" in text
    assert "/opt/image-localization-tool" in text
    assert "venv" in text or "models" in text or "config" in text
    assert "'systemctl', 'restart'" in remote


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


def test_deploy_extension_script_uses_explicit_safe_operations():
    data = EXT.read_bytes()
    # Windows PowerShell 5.1 требует BOM для русских комментариев UTF-8.
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "build-extension.py" in text
    assert "dist\\chromium" in text or "dist/chromium" in text
    assert "apps\\extension\\image-localization-tool" in text
    assert "robocopy" not in text
    assert "/MIR" not in text and "/PURGE" not in text
    assert "extension_deploy.py" in text
    assert "DryRun" in text and "Rollback" in text and "Prepare" in text
    assert "SkipBuild" in text


@pytest.mark.skipif(os.name != "nt", reason="Проверяется Windows PowerShell 5.1")
def test_extension_powershell_dry_run_with_spaces_preserves_target(tmp_path):
    """Обёртка передаёт пути с пробелами и не меняет установку при предпросмотре."""
    from scripts import extension_deploy as deploy

    source = tmp_path / "source code"
    source.mkdir()
    (source / "manifest.json").write_text('{"manifest_version":3}', encoding="utf-8")
    (source / "background.js").write_bytes(b"new")
    artifact, target = tmp_path / "fixed artifact", tmp_path / "installed extension"
    deploy.prepare(source, artifact)
    target.mkdir()
    (target / "background.js").write_bytes(b"old")
    (target / "data").mkdir()
    (target / "data/project.json").write_bytes(b"user project")
    before = deploy.snapshot(target)
    backup, plan = tmp_path / "backup copy", tmp_path / "preview plan.json"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(EXT), "-DryRun", "-Artifact", str(artifact), "-Dest", str(target),
         "-Backup", str(backup), "-Plan", str(plan)],
        cwd=ROOT, env={**os.environ, "LOCALAPPDATA": ""}, capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert plan.is_file()
    assert not backup.exists()
    assert deploy.snapshot(target) == before


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
