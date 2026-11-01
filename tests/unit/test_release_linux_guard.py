"""Guard Release Linux до checkout: gh обязан знать репозиторий."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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
    print(os.environ.get("FAKE_GH_DRAFT", "false"))
    sys.exit(0)
sys.stderr.write("unexpected gh invocation\n")
sys.exit(2)
"""


def _guard_script(text: str) -> str:
    start = text.index("name: Guard published tag")
    end = text.index("\n      - name: Checkout", start)
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


def _install_fake_gh(bin_dir: Path) -> Path:
    script = bin_dir / "fake_gh.py"
    script.write_text(_FAKE_GH, encoding="utf-8")
    return script


def _run_gh(tmp_path: Path, args: list[str], env: dict[str, str], script: Path) -> subprocess.CompletedProcess[str]:
    # Абсолютные пути обходят поиск gh.exe/gh.cmd в Windows и системный gh в Linux.
    return subprocess.run(
        [sys.executable, str(script), *args],
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
    script = _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env.pop("GH_REPO", None)
    env.pop("GITHUB_REPOSITORY", None)
    result = _run_gh(empty, ["release", "view", "v1.0.2", "--json", "isDraft", "--jq", ".isDraft"], env, script)
    assert result.returncode != 0
    assert "not a git repository" in result.stderr
    draft = (result.stdout.strip() if result.returncode == 0 else "") or ""
    assert draft != "false"


def test_gh_with_repo_in_empty_dir_sees_published_release(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
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
        script,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "false"
    assert not (empty / ".git").exists()


def test_gh_repo_env_in_empty_dir_sees_published_release(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = _install_fake_gh(bin_dir)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["GH_REPO"] = "Jawerka/image-localization-tool"
    result = _run_gh(empty, ["release", "view", "v1.0.2", "--json", "isDraft", "--jq", ".isDraft"], env, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "false"


@pytest.mark.skipif(os.name == "nt", reason="Сам Bash-guard проверяется на Linux runner; вызов заглушки — на обеих ОС")
@pytest.mark.parametrize('event,draft,exit_code,skip', [
    ('push', 'false', 0, 'true'),
    ('workflow_dispatch', 'false', 1, None),
    ('push', 'true', 0, 'false'),
])
def test_actual_guard_uses_fake_gh_and_decides_before_checkout(tmp_path, event, draft, exit_code, skip):
    """Исполнить сам run-блок YAML без сети: skip, отказ и разрешение draft."""
    script = _install_fake_gh(tmp_path)
    empty = tmp_path / 'empty'
    empty.mkdir()
    output = tmp_path / 'output.txt'
    output.touch()
    guard = _guard_script(RELEASE_WORKFLOW.read_text(encoding='utf-8'))
    body = textwrap.dedent(guard.split('run: |\n', 1)[1])
    body = body.replace('${{ github.event_name }}', event).replace('${{ inputs.tag }}', 'v1.0.2')
    env = os.environ.copy()
    env.update(FAKE_PYTHON=sys.executable, FAKE_GH=str(script), FAKE_GH_DRAFT=draft,
               GH_REPO='Jawerka/image-localization-tool', GITHUB_REPOSITORY='Jawerka/image-localization-tool',
               GITHUB_REF_NAME='v1.0.2', GITHUB_OUTPUT=str(output))
    # Функция исключает системный gh независимо от PATH и установленной авторизации.
    prefix = 'gh() { "$FAKE_PYTHON" "$FAKE_GH" "$@"; }\n'
    result = subprocess.run(['bash'], input=prefix + body, cwd=empty, env=env,
                            text=True, capture_output=True, check=False)
    assert result.returncode == exit_code, result.stderr
    recorded = output.read_text(encoding='utf-8')
    if skip is None:
        assert 'skip=' not in recorded
        assert 'Published releases are immutable' in result.stdout
    else:
        assert f'skip={skip}' in recorded
    assert not (empty / '.git').exists()
