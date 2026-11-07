"""Список исходников приёмки не включает эталоны и html."""

from pathlib import Path

from PIL import Image

from scripts.eval_intake import _write_html, is_companion_mask, list_intake_pages


def _png(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (255, 255, 255)).save(path)


def test_list_intake_pages_skips_masks_html_and_jpg_thumbnail(tmp_path):
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
    assert names == {"page.png", "sound-ref/sfx.png"}
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
