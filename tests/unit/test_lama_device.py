"""Выбор устройства LaMa: auto → cuda при доступном torch, без frozen-shortcut."""

from __future__ import annotations

import sys

from src.components import lama_inpainter


class _FakeCuda:
    def __init__(self, available: bool):
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeTorch:
    def __init__(self, available: bool):
        self.cuda = _FakeCuda(available)


def _with_torch(monkeypatch, available: bool) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(available))


def test_auto_prefers_cuda(monkeypatch):
    _with_torch(monkeypatch, True)
    assert lama_inpainter.resolve_device("auto") == "cuda"


def test_auto_falls_back_to_cpu(monkeypatch):
    _with_torch(monkeypatch, False)
    assert lama_inpainter.resolve_device("auto") == "cpu"


def test_auto_without_torch_is_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert lama_inpainter.resolve_device("auto") == "cpu"


def test_explicit_devices_win(monkeypatch):
    _with_torch(monkeypatch, False)
    assert lama_inpainter.resolve_device("cuda") == "cuda"
    assert lama_inpainter.resolve_device("cpu") == "cpu"
    assert lama_inpainter.resolve_device("") == "cpu"


def test_frozen_build_still_uses_cuda(monkeypatch):
    """Регрессия: раньше frozen форсировал cpu, теперь auto честно смотрит torch."""
    _with_torch(monkeypatch, True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert lama_inpainter.resolve_device("auto") == "cuda"
