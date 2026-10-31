"""Детект GPU: парсеры и рекомендации на фикстурах, без реальных процессов."""

from __future__ import annotations

import pytest

from src.app import hardware


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "win32")
    hardware._cache = None
    yield
    hardware._cache = None


def test_parse_nvidia_smi_reads_name_and_driver():
    text = (
        "NVIDIA GeForce RTX 5060 Laptop GPU, 617.14\n"
        "NVIDIA GeForce GTX 1050, 566.36\n"
    )
    gpus = hardware.parse_nvidia_smi(text)
    assert [gpu["name"] for gpu in gpus] == [
        "NVIDIA GeForce RTX 5060 Laptop GPU",
        "NVIDIA GeForce GTX 1050",
    ]
    assert [gpu["driver"] for gpu in gpus] == ["617.14", "566.36"]
    assert all(gpu["vendor"] == "nvidia" for gpu in gpus)


def test_parse_nvidia_smi_skips_garbage():
    assert hardware.parse_nvidia_smi("") == []
    assert hardware.parse_nvidia_smi("nvidia-smi not found") == []
    assert hardware.parse_nvidia_smi("no comma here") == []


def test_driver_major():
    assert hardware.driver_major("617.14") == 617
    assert hardware.driver_major(" 570 ") == 570
    assert hardware.driver_major("") is None
    assert hardware.driver_major("unknown") is None


def test_classify_vendor():
    assert hardware.classify_vendor("NVIDIA GeForce RTX 5060") == "nvidia"
    assert hardware.classify_vendor("AMD Radeon RX 7800 XT") == "amd"
    assert hardware.classify_vendor("Intel(R) UHD Graphics") == "intel"
    assert hardware.classify_vendor("Some Display Adapter") == "other"


def test_recommend_cu130_for_new_driver():
    recommended, reason = hardware._recommend(
        [{"vendor": "nvidia", "name": "RTX 5060", "driver": "617.14"}]
    )
    assert recommended == "torch-cu130"
    assert "617" in reason


def test_recommend_cpu_for_old_driver():
    recommended, reason = hardware._recommend(
        [{"vendor": "nvidia", "name": "GTX 1050", "driver": "566.36"}]
    )
    assert recommended == "torch-cpu"
    assert "566" in reason


def test_recommend_cpu_for_exactly_570():
    recommended, _ = hardware._recommend(
        [{"vendor": "nvidia", "name": "RTX 2080", "driver": "570.1"}]
    )
    assert recommended == "torch-cu128"


def test_recommend_cpu_for_unknown_driver():
    recommended, reason = hardware._recommend(
        [{"vendor": "nvidia", "name": "RTX 3060", "driver": ""}]
    )
    assert recommended == "torch-cpu"
    assert "неизвестна" in reason


def test_recommend_cpu_for_amd_and_intel():
    recommended, reason = hardware._recommend([{"vendor": "amd", "name": "RX 6800", "driver": ""}])
    assert recommended == "torch-cpu"
    assert "AMD" in reason
    recommended, reason = hardware._recommend([{"vendor": "intel", "name": "UHD", "driver": ""}])
    assert recommended == "torch-cpu"
    assert "Intel" in reason


def test_recommend_cpu_without_gpu():
    recommended, reason = hardware._recommend([])
    assert recommended == "torch-cpu"
    assert "NVIDIA не найдена" in reason


@pytest.mark.parametrize("driver,pack", [(569, "torch-cpu"), (570, "torch-cu128"),
                                        (579, "torch-cu128"), (580, "torch-cu130")])
def test_driver_boundaries(driver, pack):
    assert hardware._recommend([{"vendor": "nvidia", "name": "GPU", "driver": str(driver)}])[0] == pack


def test_linux_has_only_supported_cpu_pack(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "linux")
    assert hardware._recommend([{"vendor": "nvidia", "name": "GPU", "driver": "617"}])[0] == "torch-cpu"


def test_detect_prefers_nvidia_and_caches(monkeypatch):
    calls = {"count": 0}

    def fake_run(command, timeout):
        calls["count"] += 1
        if command and command[0] == "nvidia-smi":
            return "NVIDIA GeForce RTX 5060 Laptop GPU, 617.14\n"
        return ""

    monkeypatch.setattr(hardware, "_run", fake_run)
    monkeypatch.setattr(hardware, "_other_gpu_names", lambda: ["Intel(R) UHD Graphics"])
    data = hardware.detect()
    assert data["vendor"] == "nvidia"
    assert data["name"] == "NVIDIA GeForce RTX 5060 Laptop GPU"
    assert data["driver"] == 617
    assert data["recommended"] == "torch-cu130"
    assert [gpu["vendor"] for gpu in data["gpus"]] == ["nvidia", "intel"]

    first_count = calls["count"]
    cached = hardware.detect()
    assert cached == data
    assert calls["count"] == first_count

    hardware.detect(refresh=True)
    assert calls["count"] > first_count


def test_detect_without_nvidia_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(hardware, "_run", lambda command, timeout: None)
    monkeypatch.setattr(hardware, "_other_gpu_names", lambda: [])
    data = hardware.detect()
    assert data["vendor"] == "none"
    assert data["recommended"] == "torch-cpu"


def test_parse_vendor_names_drops_headers():
    text = "Name\nIntel(R) UHD Graphics\n\n"
    assert hardware.parse_vendor_names(text) == ["Intel(R) UHD Graphics"]
