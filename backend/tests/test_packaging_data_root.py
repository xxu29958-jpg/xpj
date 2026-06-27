"""Frozen-EXE data-root contract (codex review #185 P2).

When the backend runs as a PyInstaller one-file EXE, ``BACKEND_ROOT`` is the
throwaway ``_MEIPASS`` extraction dir. Files the backend *writes* — the Owner
Console settings ``.env`` and PostgreSQL backups — must instead live under
``DATA_ROOT``, which the launcher points at a persistent ``ticketbox-data/``
folder via ``TICKETBOX_DATA_DIR``. These tests lock that wiring so a future
refactor can't silently send those writes back into the throwaway _MEIPASS
bundle (where they vanish on restart).
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

import app.config as config


def _load_launch_module():
    """Import ``packaging/launch.py`` by path — it is a frozen-EXE entry script,
    not an importable package (no ``packaging/__init__.py``). Module-level code is
    only imports + defs (the ``__main__`` guard does not run under this name), so
    exec'ing it has no side effects."""
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_launch", launch_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_data_root_defaults_to_backend_root(monkeypatch):
    monkeypatch.delenv("TICKETBOX_DATA_DIR", raising=False)
    backend_root = Path("/srv/ticketbox/backend")
    assert config._resolve_data_root(backend_root) == backend_root


def test_resolve_data_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(tmp_path))
    # The backend_root argument is ignored once the override is present.
    assert config._resolve_data_root(Path("/ignored")) == tmp_path.resolve()


def test_resolve_data_root_ignores_blank_env(monkeypatch):
    monkeypatch.setenv("TICKETBOX_DATA_DIR", "   ")
    backend_root = Path("/srv/ticketbox/backend")
    assert config._resolve_data_root(backend_root) == backend_root


def test_launcher_honors_preset_data_dir(monkeypatch, tmp_path):
    """An installer/service-preset TICKETBOX_DATA_DIR (e.g. C:\\ProgramData\\...)
    must WIN. The launcher must not recompute the EXE-adjacent default and clobber
    it, or the ADR-0047 service can't run from a read-only Program Files install
    with its data in ProgramData."""
    launch = _load_launch_module()
    preset = tmp_path / "ProgramData" / "Ticketbox" / "app"
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    assert launch._resolve_writable_data_dir() == preset.resolve()


def test_launcher_defaults_next_to_bundle_when_unset(monkeypatch):
    """Unset TICKETBOX_DATA_DIR → ticketbox-data next to the EXE/bundle (dev / 档 A).
    Locks the no-behavior-change contract for the existing single-folder install."""
    launch = _load_launch_module()
    monkeypatch.delenv("TICKETBOX_DATA_DIR", raising=False)
    assert launch._resolve_writable_data_dir() == launch._bundle_dir() / "ticketbox-data"


def test_launcher_ignores_blank_preset(monkeypatch):
    launch = _load_launch_module()
    monkeypatch.setenv("TICKETBOX_DATA_DIR", "   ")
    assert launch._resolve_writable_data_dir() == launch._bundle_dir() / "ticketbox-data"


def test_configure_environment_mkdirs_preset_not_exe_adjacent(monkeypatch, tmp_path):
    """configure_environment must mkdir + normalize the PRESET dir (not the
    EXE-adjacent default) and leave the env pointing there for app.config."""
    launch = _load_launch_module()
    preset = tmp_path / "preset-data"
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    returned = launch.configure_environment()
    assert returned == preset.resolve()
    assert (preset / "uploads").is_dir()
    assert os.environ["TICKETBOX_DATA_DIR"] == str(preset.resolve())


def test_writable_dirs_follow_data_root_override(tmp_path):
    """settings .env + backups must re-anchor when DATA_ROOT is redirected.

    Simulates the frozen build, where DATA_ROOT (ticketbox-data/) diverges from
    BACKEND_ROOT (_MEIPASS). Reloads the leaf service modules so their
    module-level path constants recompute against the redirected DATA_ROOT, then
    restores the real value so no other test is affected.
    """
    original = config.DATA_ROOT
    config.DATA_ROOT = tmp_path
    try:
        backup_service = importlib.reload(importlib.import_module("app.services.backup_service"))
        runtime_settings = importlib.reload(importlib.import_module("app.services.runtime_settings_service"))
        expected_backups = tmp_path / "backups"
        expected_env = tmp_path / ".env"
        assert expected_backups == backup_service._BACKUP_DIR
        assert expected_env == runtime_settings._ENV_PATH
    finally:
        config.DATA_ROOT = original
        importlib.reload(importlib.import_module("app.services.backup_service"))
        importlib.reload(importlib.import_module("app.services.runtime_settings_service"))
