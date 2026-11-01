"""Guard Release Linux до checkout: gh обязан знать репозиторий."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

_FAKE_GH = r"""
import os
import sys

args = sys.argv[1:]
repo = os.environ.get("GH_REPO")
if "--repo" in args:
    repo = args[args.index("--repo") + 1]
if not repo:
    sys.stderr.write("fatal: not a git repository (or any of the parent directories): .git\n")
    sys.exit(1)
if args[:2] == ["release", "view"]:
    print("false")
    sys.exit(0)
sys.stderr.write("unexpected gh invocation\n")
sys.exit(2)
"""


def _guard_script(text: str) -> str:
    start = text.index("name: Guard published tag")
    end = text.index("name: Checkout")
    return text[start:end]


def _job_env_block(text: str) -> str:
    start = text.index("jobs:")
    end = text.index("steps:")
    return text[start:end]


def _gh_lines(script: str) -> list[str]:
    lines = []
    for raw in script.splitlines():
        stripped = raw.strip().rstrip("\\").strip()
        if re.search(r"(?:^|[\s;`|$()])gh\s+release\s", stripped):
            lines.append(stripped)
    return lines


def _install_fake_gh(bin_dir: Path) -> None:
    script = bin_dir / "fake_gh.py"
    script.write_text(_FAKE_GH, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "gh.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="ascii",
        )
    else:
        gh = bin_dir / "gh"
        gh.write_text(f"#!/usr/bin/env python3\n{script.read_text(encoding='utf-8')}", encoding="utf-8")
        gh.chmod(0o755)


def _run_gh(tmp_path: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_workflow_sets_gh_repo_before_checkout():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    env_block = _job_env_block(text)
    assert "GH_REPO: ${{ github.repository }}" in env_block
    assert text.index("GH_REPO: ${{ github.repository }}") < text.index("name: Guard published tag")
    assert text.index("name: Guard published tag") < text.index("name: Checkout")


def test_every_gh_call_in_release_workflow_passes_repo():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    commands = _gh_lines(text)
    assert commands
    for command in commands:
        assert "--repo" in command, command
        assert "$GITHUB_REPOSITORY" in command, command


def test_guard_view_line_names_repository():
    guard = _guard_script(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    commands = _gh_lines(guard)
    assert len(commands) == 1
    assert commands[0].startswith("DRAFT=\"$(gh release view")
    assert '--repo "$GITHUB_REPOSITORY"' in commands[0]


def test_gh_without_repo_in_empty_dir_is_hidden_by_or_true(tmp_path):
    """Репродукция: пустой cwd, нет --repo → not a git repository, `|| true` даёт skip=false."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.pop("GH_REPO", None)
    env.pop("GITHUB_REPOSITORY", None)
    result = _run_gh(empty, ["release", "view", "v1.0.2", "--json", "isDraft", "--jq", ".isDraft"], env)
    assert result.returncode != 0
    assert "not a git repository" in result.stderr
    draft = (result.stdout.strip() if result.returncode == 0 else "") or ""
    assert draft != "false"


def test_gh_with_repo_in_empty_dir_sees_published_release(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.pop("GH_REPO", None)
    result = _run_gh(
        empty,
        [
            "release",
            "view",
            "v1.0.2",
            "--json",
            "isDraft",
            "--jq",
            ".isDraft",
            "--repo",
            "Jawerka/image-localization-tool",
        ],
        env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "false"
    assert not (empty / ".git").exists()


def test_gh_repo_env_in_empty_dir_sees_published_release(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["GH_REPO"] = "Jawerka/image-localization-tool"
    result = _run_gh(empty, ["release", "view", "v1.0.2", "--json", "isDraft", "--jq", ".isDraft"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "false"
