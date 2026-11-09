"""Список исходников приёмки не включает эталоны и html."""

from pathlib import Path

import pytest
from PIL import Image

from scripts.eval_intake import _write_html, is_companion_mask, list_intake_pages


def _png(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (255, 255, 255)).save(path)


def test_list_intake_pages_preserves_distinct_same_stem_sources(tmp_path):
    root = tmp_path / "test-img"
    _png(root / "page.png")
    _png(root / "page_mask.png")
    _png(root / "other-mask.png")
    _png(root / "other-mask-2.png")
    _png(root / "sound-ref" / "sfx.png")
    _png(root / "sound-ref" / "sfx_mask.png")
    _png(root / "html" / "saved.png")
    Image.new("RGB", (2, 2), (0, 0, 0)).save(root / "page.jpg")

    names = {path.relative_to(root).as_posix() for path in list_intake_pages(root)}
    assert names == {"page.png", "page.jpg", "sound-ref/sfx.png"}
    assert not is_companion_mask(root / "page.png")
    assert is_companion_mask(root / "page_mask.png")
    assert is_companion_mask(root / "other-mask-2.png")


def test_write_html_stacks_result_and_stars(tmp_path):
    out = tmp_path / "intake-demo"
    out.mkdir()
    _write_html(
        out,
        [
            {
                "stem": "page",
                "folder": "page",
                "ocr_engine": "vlm",
                "translator_engine": "llm",
                "regions": 2,
                "overflow": [],
                "min_font": 12,
                "seconds": 1.2,
                "eval": {"ink_recall": 1.0},
            }
        ],
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "page/result.png" in html
    assert "data-star='5'" in html
    assert "localStorage" in html
    assert "#121214" in html
    assert "#e8e8ea" in html
    assert "#e2a100" in html


def test_same_stem_output_and_html_identities_are_independent(tmp_path):
    from scripts.eval_intake import _folder_name

    root = tmp_path / "images"
    _png(root / "page.png")
    Image.new("RGB", (2, 2)).save(root / "page.jpg")
    paths = list_intake_pages(root)
    folders = [_folder_name(path, root) for path in paths]
    assert len(set(folders)) == 2
    out = tmp_path / "report"
    out.mkdir()
    _write_html(out, [{"stem": path.stem, "file": path.name, "folder": folder}
                      for path, folder in zip(paths, folders)])
    html = (out / 'index.html').read_text(encoding='utf-8')
    for folder in folders:
        assert f"data-stem='{folder}'" in html
        assert f"id='p-{folder}'" in html
        assert f"{folder}/result.png" in html




@pytest.mark.parametrize('failures,expected', [(0, 0), (1, 1), (2, 2)])
def test_main_reports_processing_failures_without_losing_successes(tmp_path, monkeypatch, failures, expected):
    import json
    import sys
    from scripts import eval_intake

    root = tmp_path / 'images'
    _png(root / 'one.png')
    _png(root / 'two.png')
    out = tmp_path / 'report'
    monkeypatch.setattr(sys, 'argv', ['eval_intake', '--images', str(root), '--out', str(out)])
    monkeypatch.setattr(eval_intake, 'PagePipeline', lambda config: object())
    monkeypatch.setattr(eval_intake, 'annotation_index', lambda root: {})
    monkeypatch.setattr(eval_intake.Config, 'load', lambda: eval_intake.Config())
    count = 0

    def process(*args):
        nonlocal count
        count += 1
        if count <= failures:
            raise RuntimeError('controlled failure')
        source = args[1]
        return {'stem': source.stem, 'file': source.name, 'folder': source.name,
                'ocr_engine': 'fake', 'translator_engine': 'fake', 'seconds': 0}

    monkeypatch.setattr(eval_intake, 'process_page', process)
    assert eval_intake.main() == expected
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    assert summary == {'total': 2, 'succeeded': 2 - failures, 'failed': failures,
                       'exit_code': expected, 'status': ['success', 'partial', 'failed'][expected]}
    notes = json.loads((out / 'visual-notes.json').read_text(encoding='utf-8'))
    assert len(notes) == 2
    registry = json.loads((out / 'intake-registry.json').read_text(encoding='utf-8'))
    assert [row['execution_status'] for row in notes] == [row['execution_status'] for row in registry]
    assert sum(row['execution_status'] == 'failed' for row in registry) == failures
    assert all(row['status'] == 'pending' for row in registry)
    assert (out / 'index.html').exists()
