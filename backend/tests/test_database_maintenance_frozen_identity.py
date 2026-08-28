"""Frozen backend and migrator executable identity boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location(
        "ticketbox_database_maintenance_frozen_identity_launch",
        launch_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_backend_and_helper_identities_are_separate(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        launch.sys,
        "argv",
        ["ticketbox-backend.exe", "--fresh-schema-upgrade"],
    )
    monkeypatch.setattr(
        launch.sys,
        "executable",
        "C:/Program Files/Ticketbox/ticketbox-backend.exe",
    )
    with pytest.raises(RuntimeError, match="dedicated frozen helper"):
        launch.main()

    monkeypatch.setattr(
        launch.sys,
        "argv",
        ["ticketbox-database-maintenance.exe"],
    )
    monkeypatch.setattr(
        launch.sys,
        "executable",
        "C:/Program Files/Ticketbox/ticketbox-database-maintenance.exe",
    )
    with pytest.raises(RuntimeError, match="requires an explicit mode"):
        launch.main()
