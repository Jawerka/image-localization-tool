"""Компоненты ищут модели через нейтральный API."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "src" / "components"


def test_components_do_not_import_app_layer():
    for path in COMPONENTS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src.app"), path.name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("src.app"), path.name
