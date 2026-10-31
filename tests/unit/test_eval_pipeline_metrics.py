"""Дополнительные поля evaluation не требуют обязательных профилировщиков."""

import sys
from pathlib import Path

from PIL import Image

from scripts.eval_pipeline import RssSampler, find_pairs


def test_rss_sampler_returns_current_process_fields():
    sampler = RssSampler(interval=0.001)
    sampler.start()
    sample = sampler.stop()
    assert set(sample) == {"rss_start_bytes", "rss_peak_bytes", "rss_end_bytes"}
    values = [value for value in sample.values() if value is not None]
    assert all(value >= 0 for value in values)
    if values:
        assert sample["rss_peak_bytes"] >= sample["rss_start_bytes"]


def test_rss_sampler_is_optional_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    sampler = RssSampler()
    sampler.start()
    assert sampler.stop() == {
        "rss_start_bytes": None,
        "rss_peak_bytes": None,
        "rss_end_bytes": None,
    }


def _png(path: Path, color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", (8, 8), color).save(path)


def test_find_pairs_reads_nested_masks_and_balloon_zone(tmp_path):
    page = tmp_path / "comic"
    nested = page / "sound-ref"
    nested.mkdir(parents=True)
    _png(page / "0001.png", (255, 255, 255, 255))
    _png(page / "0001-mask.png", (255, 0, 0, 255))
    _png(page / "0001-mask-2.png", (255, 0, 0, 255))
    _png(nested / "new-sound-ref (1).png", (255, 255, 255, 255))
    _png(nested / "new-sound-ref (1)_mask.png", (255, 0, 0, 255))
    _png(page / "orphan-mask.png", (255, 0, 0, 255))

    pairs = find_pairs(page)
    by_name = {image.name: (mask.name, zone.name if zone else None) for image, mask, zone in pairs}
    assert by_name["0001.png"] == ("0001-mask.png", "0001-mask-2.png")
    assert by_name["new-sound-ref (1).png"] == ("new-sound-ref (1)_mask.png", None)
    assert "orphan-mask.png" not in by_name
