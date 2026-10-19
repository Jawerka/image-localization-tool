"""Дополнительные поля evaluation не требуют обязательных профилировщиков."""

import sys

from scripts.eval_pipeline import RssSampler


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
