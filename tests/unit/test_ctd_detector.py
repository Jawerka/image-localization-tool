"""Подставная сессия comic-text-detector: бокс, отсев и карта seg."""

import numpy as np
from PIL import Image

from src.components.ctd_detector import ComicTextDetector, clip_outlined_mask
from src.models import TextRegion


class _FakeSession:
    def __init__(self, rows, seg):
        self.rows = rows
        self.seg = seg

    def run(self, _names, feeds):
        assert feeds["images"].shape == (1, 3, 1024, 1024)
        blk = np.zeros((1, 8, 7), np.float32)
        for index, row in enumerate(self.rows):
            blk[0, index, :len(row)] = row
        seg = self.seg.astype(np.float32)[None, None]
        det = np.zeros((1, 2, 1024, 1024), np.float32)
        return [blk, seg, det]


def test_fake_session_returns_page_box_and_seg():
    """Letterbox 200×100: бокс в центре сети попадает на страницу, слабый отбрасывается."""
    seg = np.zeros((1024, 1024), np.float32)
    seg[492:532, 462:562] = 1.0
    session = _FakeSession(
        [
            [512, 512, 100, 40, 0.95, 0.9, 0.05],
            [512, 512, 100, 40, 0.2, 0.9, 0.05],
            [512, 512, 96, 38, 0.9, 0.2, 0.8],
        ],
        seg,
    )
    page = ComicTextDetector(session=session, conf=0.4).detect(Image.new("RGB", (200, 100), "white"))
    assert len(page.boxes) == 1
    x, y, w, h = page.boxes[0].bbox
    assert page.boxes[0].class_name == "text_free"
    assert 70 < x < 110
    assert 30 < y < 70
    assert w > 8 and h > 4
    assert page.seg.shape == (100, 200)
    assert page.seg[y + h // 2, x + w // 2] == 255
    assert page.seg[0, 0] == 0


def test_offline_ctd_read_keeps_a_sound_and_drops_a_letter():
    """Без языковой модели остаётся только звук из двух и более букв."""
    from PIL import Image

    from src.components.rapid_ocr import OcrWord, RapidOcr
    from src.config import Config
    from src.page_pipeline import PagePipeline

    pipe = PagePipeline(Config(ocr_backend="rapid", sfx_mode="replace", detector_mode="both"))
    ocr = RapidOcr()

    def words(image):
        text = "BOOM" if image.size[0] >= 40 else "A"
        return [OcrWord(text, (2, 2, 12, 8), 0.99)]

    ocr._words = words
    pipe.ocr = ocr
    pipe.ocr_name = "rapid"
    sound = TextRegion(1, (0, 0, 48, 24), text="")
    sound.from_ctd = True
    junk = TextRegion(2, (0, 0, 16, 16), text="")
    junk.from_ctd = True
    kept = pipe._keep_ctd_reads(Image.new("RGB", (80, 40), "white"), [sound, junk])
    assert [region.text for region in kept] == ["BOOM"]
    assert kept[0].block_type == "sfx"


def test_auto_with_rapid_does_not_call_second_detector(monkeypatch):
    """Без языковой модели auto остаётся на основном детекторе."""
    from src.config import Config
    from src.page_pipeline import PagePipeline

    pipe = PagePipeline(Config(
        ocr_backend="rapid",
        detector_mode="auto",
        sfx_mode="replace",
        discover_missing_text=False,
        adaptive_text=False,
        layout_long_side=0,
    ))
    pipe.ocr = object()
    pipe.ocr_name = "rapid"
    calls = []
    monkeypatch.setattr(pipe, "_detect", lambda _image: [])
    monkeypatch.setattr(pipe, "_read_ctd", lambda *_args, **_kwargs: calls.append(True))
    pipe.analyze(Image.new("RGB", (32, 32), "white"), "page.png", "en", "ru")
    assert calls == []


def test_auto_with_vlm_calls_second_detector(monkeypatch):
    """При живой языковой модели auto дочитывает боксы второго детектора."""
    from src.config import Config
    from src.page_pipeline import PagePipeline

    pipe = PagePipeline(Config(
        ocr_backend="vlm",
        detector_mode="auto",
        sfx_mode="replace",
        discover_missing_text=False,
        adaptive_text=False,
        layout_long_side=0,
    ))
    pipe.ocr = object()
    pipe.ocr_name = "vlm"
    calls = []

    def _read(_image, _warnings, quiet=False):
        calls.append(quiet)
        return None

    monkeypatch.setattr(pipe, "_detect", lambda _image: [])
    monkeypatch.setattr(pipe, "_read_ctd", _read)
    pipe.analyze(Image.new("RGB", (32, 32), "white"), "page.png", "en", "ru")
    assert calls == [True]


def test_auto_missing_model_file_is_quiet(monkeypatch):
    """В auto нет файла — без предупреждения. Явный режим «оба» предупреждает."""
    from pathlib import Path

    from src.config import Config
    from src.page_pipeline import PagePipeline

    monkeypatch.setattr(
        "src.utils.paths.resolve_model",
        lambda *_args, **_kwargs: Path("missing-comictextdetector.pt.onnx"),
    )
    image = Image.new("RGB", (16, 16), "white")
    quiet_pipe = PagePipeline(Config(detector_mode="auto", sfx_mode="replace"))
    quiet = []
    assert quiet_pipe._read_ctd(image, quiet, quiet=True) is None
    assert quiet == []

    loud_pipe = PagePipeline(Config(detector_mode="both", sfx_mode="replace"))
    loud = []
    assert loud_pipe._read_ctd(image, loud, quiet=False) is None
    assert any("не найден" in item for item in loud)


def test_clip_keeps_outlined_ink_inside_seg_only():
    """Маска обведённого звука вне расширенной карты срезается, чужая маска остаётся."""
    mask = np.zeros((40, 80), np.uint8)
    mask[10:20, 10:30] = 255
    mask[10:20, 50:70] = 255
    seg = np.zeros_like(mask)
    seg[8:22, 8:32] = 255
    outlined = TextRegion(1, (8, 8, 24, 14), block_type="sfx")
    outlined._outline_ink = True
    other = TextRegion(2, (48, 8, 24, 14), block_type="sfx")
    clipped = clip_outlined_mask(mask, [outlined, other], seg, dilate_px=1)
    assert clipped[15, 20] == 255
    assert clipped[15, 60] == 255
    mask[10:20, 34:46] = 255
    outlined.bbox = (8, 8, 40, 14)
    clipped = clip_outlined_mask(mask, [outlined], seg, dilate_px=1)
    assert clipped[15, 40] == 0
    assert clipped[15, 20] == 255
