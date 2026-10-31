"""Выбор режима сравнивает одиночный детектор с парой, а не с лучшей клеткой."""

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "ab_detectors.py"
    spec = importlib.util.spec_from_file_location("ab_detectors", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(name, recall, hit, seconds=1.0):
    return {
        "name": name,
        "metrics": {"recall": recall, "hit6": hit},
        "timings": {"detect": seconds},
    }


def test_low_threshold_cell_does_not_force_both():
    """Порог 0.15 лучше по попаданию, но пара не лучше основного — остаётся один детектор."""
    verdict = _module()._verdict({
        "offline": {
            "A-ogkalu": [_row("page.png", 0.90, 0.90)],
            "B-both": [_row("page.png", 0.90, 0.90, 3.0)],
            "C-ctd": [_row("page.png", 0.40, 0.40)],
            "D-ogkalu-low": [_row("page.png", 0.90, 0.99)],
        },
    })
    assert verdict["choice"] == "ogkalu"
    assert verdict["pages"] == []


def test_pair_wins_when_it_beats_the_primary():
    verdict = _module()._verdict({
        "offline": {
            "A-ogkalu": [_row("page.png", 0.90, 0.90)],
            "B-both": [_row("page.png", 0.96, 0.90, 3.0)],
        },
    })
    assert verdict["choice"] == "both"
    assert verdict["pages"] == ["page.png"]


def test_reported_pages_belong_to_the_closer_detector():
    """Длинный проигрыш только второго детектора не подменяет страницы основного."""
    verdict = _module()._verdict({
        "offline": {
            "A-ogkalu": [_row("only.png", 0.90, 0.90), _row("ok.png", 0.90, 0.90)],
            "B-both": [_row("only.png", 0.90, 0.96, 3.0), _row("ok.png", 0.90, 0.90, 3.0)],
            "C-ctd": [_row("only.png", 0.10, 0.10), _row("ok.png", 0.10, 0.10)],
        },
    })
    assert verdict["choice"] == "both"
    assert verdict["pages"] == ["only.png"]


def test_verdict_uses_vlm_table_when_offline_is_empty():
    verdict = _module()._verdict({
        "offline": {},
        "vlm": {
            "A-ogkalu": [_row("sound.png", 0.80, 0.90)],
            "B-both": [_row("sound.png", 0.80, 0.90, 4.0)],
        },
    })
    assert verdict["choice"] == "ogkalu"
