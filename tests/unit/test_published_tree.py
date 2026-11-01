"""Чистый опубликованный набор файлов не тащит legacy."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_git_index_omits_legacy_and_data():
    listed = subprocess.check_output(
        ["git", "ls-files", "legacy", "data", "models"],
        cwd=ROOT,
        text=True,
    )
    assert listed.strip() == ""


def test_history_doc_keeps_old_sha():
    text = (ROOT / "docs" / "HISTORY.md").read_text(encoding="utf-8")
    assert "c498ba2271a2e9470bf2db92774ee2b8719bfbf7" in text
