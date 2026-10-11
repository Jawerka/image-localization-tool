"""CLI --deploy: разбор аргументов и прогон с подменёнными загрузчиками."""

from __future__ import annotations

from pathlib import Path

from src.app import deploy, runtime
from src.app.desktop import parse_args


def test_parse_deploy_flag():
    args = parse_args(["--deploy", "cpu", "argos"])
    assert args.deploy == ["cpu", "argos"]
    assert parse_args(["--deploy", "all"]).deploy == ["all"]
    assert parse_args(["page.png"]).deploy == []


def test_normalize_expands_all(monkeypatch):
    monkeypatch.setattr(
        "src.app.hardware.detect",
        lambda refresh=False: {"recommended": "torch-cu128"},
    )
    assert deploy.normalize(["all"]) == ["models", "argos", "cuda"]
    monkeypatch.setattr(
        "src.app.hardware.detect",
        lambda refresh=False: {"recommended": "torch-cpu"},
    )
    assert deploy.normalize(["models", "cpu", "models"]) == ["models", "cpu"]
    assert deploy.normalize([]) == []
    assert deploy.normalize(["bogus"]) == []


def test_run_models_downloads_three_kinds(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(deploy.model_manager, "dest_dir", lambda kind, override=None: tmp_path)
    monkeypatch.setattr(
        deploy.model_manager,
        "download",
        lambda kind, dest, progress=None: calls.append(kind) or tmp_path / kind,
    )
    monkeypatch.setattr(
        deploy.model_manager,
        "download_font_pack",
        lambda dest, progress=None: tmp_path,
    )
    assert deploy.run(["models"]) == 0
    assert calls == ["detector", "lama", "font"]


def test_run_pack_installs(monkeypatch, tmp_path):
    pack = runtime.Pack("argos", "Argos", "argos", runtime.platform_tag(), "310", "1.0", "", "", 0)
    installed: list[str] = []
    monkeypatch.setattr(deploy.runtime, "pack_by_id", lambda pack_id: pack)
    monkeypatch.setattr(deploy.runtime, "is_installed", lambda pack_id: False)
    monkeypatch.setattr(
        deploy.runtime,
        "download_and_install",
        lambda target, progress=None: installed.append(target.id) or tmp_path,
    )
    monkeypatch.setattr(deploy.runtime, "pack_dir", lambda pack_id: tmp_path)
    monkeypatch.setattr(deploy.runtime, "activate_path", lambda directory: True)
    assert deploy.run(["argos"]) == 0
    assert installed == ["argos"]


def test_run_pack_already_installed_activates(monkeypatch, tmp_path):
    pack = runtime.Pack("torch-cpu", "CPU", "torch", runtime.platform_tag(), "310", "1.0", "", "", 0)
    activated: list[Path] = []
    monkeypatch.setattr(deploy.runtime, "pack_by_id", lambda pack_id: pack)
    monkeypatch.setattr(deploy.runtime, "is_installed", lambda pack_id: True)
    monkeypatch.setattr(deploy.runtime, "pack_dir", lambda pack_id: tmp_path)
    monkeypatch.setattr(
        deploy.runtime, "activate_path", lambda directory: activated.append(Path(directory)) or True
    )
    monkeypatch.setattr(
        deploy.runtime,
        "download_and_install",
        lambda target, progress=None: (_ for _ in ()).throw(AssertionError("не должен качать")),
    )
    assert deploy.run(["cpu"]) == 0
    assert activated == [tmp_path]


def test_run_reports_failure(monkeypatch, tmp_path):
    pack = runtime.Pack("argos", "Argos", "argos", runtime.platform_tag(), "310", "1.0", "", "", 0)
    monkeypatch.setattr(deploy.runtime, "pack_by_id", lambda pack_id: pack)
    monkeypatch.setattr(deploy.runtime, "is_installed", lambda pack_id: False)
    monkeypatch.setattr(deploy.runtime, "pack_dir", lambda pack_id: tmp_path)
    monkeypatch.setattr(
        deploy.runtime,
        "download_and_install",
        lambda target, progress=None: (_ for _ in ()).throw(RuntimeError("сеть")),
    )
    assert deploy.run(["argos"]) == 1
