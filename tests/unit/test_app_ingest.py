"""Список изображений, распаковка архивов и план глав."""

import io
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from src.app.ingest import (
    NoImagesError,
    archive_images,
    extract_archive,
    is_archive,
    list_images,
    natural_sort_key,
    plan_chapters,
)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (8, 8, 8)).save(buffer, format="PNG")
    return buffer.getvalue()


def _save(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), (8, 8, 8)).save(path)


def test_natural_sort_key_numeric_and_casefold():
    assert natural_sort_key("page2") < natural_sort_key("page10")
    assert natural_sort_key("Page2") < natural_sort_key("page10")
    assert natural_sort_key("Page2.png") == natural_sort_key("page2.PNG")
    ordered = sorted(["page10.png", "Page2.png", "page2.png"], key=natural_sort_key)
    assert ordered[0:2] == ["Page2.png", "page2.png"]
    assert ordered[-1] == "page10.png"


def test_list_images_filters_order_and_recursion(tmp_path):
    root = tmp_path / "pages"
    _save(root / "Page2.png")
    _save(root / "page10.png")
    _save(root / "scan.jpg")
    _save(root / "extra.jpeg")
    _save(root / "art.bmp")
    _save(root / "plate.tif")
    _save(root / "other.tiff")
    _save(root / "skip" / "page2.png")
    _save(root / "sub" / "nested.png")
    (root / "note.txt").write_text("нет", encoding="utf-8")
    (root / "not-a-file.png").mkdir()

    flat = [path.relative_to(root).as_posix() for path in list_images(root, False)]
    assert flat == [
        "art.bmp",
        "extra.jpeg",
        "other.tiff",
        "Page2.png",
        "page10.png",
        "plate.tif",
        "scan.jpg",
    ]
    assert "note.txt" not in flat
    assert all("/" not in name for name in flat)

    nested = [path.relative_to(root).as_posix() for path in list_images(root, True)]
    assert nested == flat + ["skip/page2.png", "sub/nested.png"]
    assert nested.index("Page2.png") < nested.index("page10.png")

    assert list_images(tmp_path / "missing", True) == []
    lone = tmp_path / "lone.png"
    _save(lone)
    assert list_images(lone, False) == []


@pytest.mark.parametrize("suffix", [".zip", ".cbz"])
def test_extract_archive_images_natural_order(tmp_path, suffix):
    archive = tmp_path / f"book{suffix}"
    png = _png_bytes()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("page10.png", png)
        bundle.writestr("vol/page3.png", png)
        bundle.writestr("page2.png", png)
        bundle.writestr("notes.txt", b"skip")
        bundle.writestr("empty/", b"")
        bundle.writestr("empty/readme.txt", b"skip")
    dest = tmp_path / "out" / "pages"
    extracted = extract_archive(archive, dest)
    assert [path.relative_to(dest).as_posix() for path in extracted] == [
        "page2.png",
        "page10.png",
        "vol/page3.png",
    ]
    assert extracted[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (dest / "notes.txt").exists()
    assert not (dest / "empty" / "readme.txt").exists()


@pytest.mark.parametrize("suffix", [".zip", ".cbz"])
def test_extract_archive_skips_zip_slip(tmp_path, suffix):
    dest = tmp_path / "dest"
    archive = tmp_path / f"slip{suffix}"
    outside = tmp_path / "evil.png"
    absolute = tmp_path / "abs-evil.png"
    png = _png_bytes()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../evil.png", png)
        bundle.writestr("foo/../../evil2.png", png)
        bundle.writestr(absolute.as_posix(), png)
        bundle.writestr("ok/page.png", png)
    extracted = extract_archive(archive, dest)
    assert [path.relative_to(dest).as_posix() for path in extracted] == ["ok/page.png"]
    assert not outside.exists()
    assert not absolute.exists()
    assert not (tmp_path / "evil2.png").exists()
    leaked = [
        path.name
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name.startswith("evil")
    ]
    assert leaked == []
    assert (dest / "ok" / "page.png").is_file()


def test_is_archive_suffix():
    assert is_archive(Path("Book.CBZ"))
    assert is_archive(Path("book.zip"))
    assert is_archive(Path("book.rar"))
    assert is_archive(Path("book.cbr"))
    assert is_archive(Path("book.cb7"))
    assert is_archive(Path("book.7z"))
    assert is_archive(Path("book.cbt"))
    assert is_archive(Path("book.tar"))
    assert not is_archive(Path("page.PNG"))
    assert not is_archive(Path("notes.txt"))


def test_extract_archive_empty_raises(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("notes.txt", b"skip")
    dest = tmp_path / "out"
    with pytest.raises(NoImagesError, match="переводить нечего"):
        extract_archive(archive, dest)
    assert not dest.exists()


def test_extract_archive_depth_and_mask(tmp_path):
    archive = tmp_path / "deep.cbz"
    png = _png_bytes()
    keep = "a/b/c/d/e/page.png"
    too_deep = "a/b/c/d/e/f/page.png"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(keep, png)
        bundle.writestr(too_deep, png)
        bundle.writestr("cover-mask.png", png)
    only_deep = tmp_path / "only-deep.zip"
    with zipfile.ZipFile(only_deep, "w") as bundle:
        bundle.writestr(too_deep, png)
    dest = tmp_path / "out"
    extracted = extract_archive(archive, dest)
    assert [path.relative_to(dest).as_posix() for path in extracted] == [keep]
    assert archive_images(archive) == [keep]
    assert not (dest / "cover-mask.png").exists()
    with pytest.raises(NoImagesError, match="переводить нечего"):
        archive_images(only_deep)


def test_cbr_with_zip_payload(tmp_path):
    archive = tmp_path / "book.cbr"
    png = _png_bytes()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("page.png", png)
    extracted = extract_archive(archive, tmp_path / "out")
    assert [path.name for path in extracted] == ["page.png"]


def test_extract_tar_skips_link_and_slip(tmp_path):
    archive = tmp_path / "book.cbt"
    png = _png_bytes()
    with tarfile.open(archive, "w") as bundle:
        info = tarfile.TarInfo("ch/page.png")
        info.size = len(png)
        bundle.addfile(info, io.BytesIO(png))
        link = tarfile.TarInfo("ch/link.png")
        link.type = tarfile.SYMTYPE
        link.linkname = "page.png"
        bundle.addfile(link)
        slip = tarfile.TarInfo("../evil.png")
        slip.size = len(png)
        bundle.addfile(slip, io.BytesIO(png))
    dest = tmp_path / "out"
    extracted = extract_archive(archive, dest)
    assert [path.relative_to(dest).as_posix() for path in extracted] == ["ch/page.png"]
    assert not (tmp_path / "evil.png").exists()
    assert not (dest / "ch" / "link.png").exists()


def test_extract_7z(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    archive = tmp_path / "book.cb7"
    png = _png_bytes()
    with py7zr.SevenZipFile(archive, "w") as bundle:
        bundle.writestr(png, "page10.png")
        bundle.writestr(png, "page2.png")
        bundle.writestr(b"no", "notes.txt")
    dest = tmp_path / "out"
    extracted = extract_archive(archive, dest)
    assert [path.relative_to(dest).as_posix() for path in extracted] == [
        "page2.png",
        "page10.png",
    ]
    assert not (dest / "notes.txt").exists()


def _rar_exe() -> str | None:
    found = shutil.which("rar")
    if found:
        return found
    root = os.environ.get("ProgramFiles", "")
    candidate = Path(root) / "WinRAR" / "Rar.exe"
    if candidate.is_file():
        return str(candidate)
    return None


def test_extract_rar(tmp_path):
    pytest.importorskip("rarfile")
    rar = _rar_exe()
    if rar is None:
        pytest.skip("нет rar для сборки архива")
    page = tmp_path / "page2.png"
    _save(page)
    archive = tmp_path / "book.cbr"
    subprocess.run(
        [rar, "a", "-ep", str(archive), str(page)],
        check=True,
        capture_output=True,
    )
    extracted = extract_archive(archive, tmp_path / "out")
    assert [path.name for path in extracted] == ["page2.png"]


def test_rar_without_tool_explains(tmp_path, monkeypatch):
    rarfile = pytest.importorskip("rarfile")
    rar = _rar_exe()
    if rar is None:
        pytest.skip("нет rar для сборки архива")
    page = tmp_path / "page.png"
    _save(page)
    archive = tmp_path / "book.rar"
    subprocess.run(
        [rar, "a", "-ep", str(archive), str(page)],
        check=True,
        capture_output=True,
    )

    def _boom(self, info, pwd=None):
        raise rarfile.RarCannotExec("Cannot find working tool")

    monkeypatch.setattr(rarfile.RAR5Parser, "open", _boom)
    monkeypatch.setattr(rarfile.RAR3Parser, "open", _boom)
    with pytest.raises(ValueError, match="7-Zip или UnRAR"):
        extract_archive(archive, tmp_path / "out")


def test_plan_chapters_flat_is_empty(tmp_path):
    root = tmp_path / "in"
    paths = [root / "ch1" / "page.png", root / "page.png"]
    assert plan_chapters(paths, "flat", root=root, archive_stem="Vol") == [
        (paths[0], ""),
        (paths[1], ""),
    ]
    assert plan_chapters(list(reversed(paths)), "other", root=root) == [
        (paths[1], ""),
        (paths[0], ""),
    ]


def test_plan_chapters_subdir_folder(tmp_path):
    root = tmp_path / "in"
    nested = root / "ch1" / "page.png"
    deep = root / "ch1" / "sub" / "tail.png"
    top = root / "page.png"
    assert plan_chapters([nested, top, deep], "subdir", root=root) == [
        (nested, "ch1"),
        (top, ""),
        (deep, "ch1"),
    ]


def test_plan_chapters_subdir_archive_stem(tmp_path):
    root = tmp_path / "extracted"
    loose = [root / "page2.png", root / "page10.png"]
    assert plan_chapters(loose, "subdir", root=root, archive_stem="Vol.1") == [
        (loose[0], "Vol.1"),
        (loose[1], "Vol.1"),
    ]

    packed = [root / "Chapter" / "page2.png", root / "Chapter" / "extra" / "page10.png"]
    assert plan_chapters(packed, "subdir", root=root, archive_stem="Vol.1") == [
        (packed[0], "Chapter"),
        (packed[1], "Chapter"),
    ]

    mixed = [root / "loose.png", root / "ch1" / "page.png"]
    assert plan_chapters(mixed, "subdir", root=root, archive_stem="Vol.1") == [
        (mixed[0], ""),
        (mixed[1], "ch1"),
    ]
    split = [root / "a" / "one.png", root / "b" / "two.png"]
    assert plan_chapters(split, "subdir", root=root, archive_stem="Vol.1") == [
        (split[0], "a"),
        (split[1], "b"),
    ]
    outside = tmp_path / "side" / "page.png"
    assert plan_chapters([outside], "subdir", root=root, archive_stem="Vol.1") == [
        (outside, ""),
    ]
    assert plan_chapters([], "subdir", root=root, archive_stem="Vol.1") == []
