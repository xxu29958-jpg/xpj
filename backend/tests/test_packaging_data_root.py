"""Frozen-EXE data-root contract (codex review #185 P2).

When the backend runs as a PyInstaller one-file EXE, ``BACKEND_ROOT`` is the
throwaway ``_MEIPASS`` extraction dir. Files the backend *writes* — the Owner
Console settings ``.env`` and SQLite backups — must instead live under
``DATA_ROOT``, which the launcher points at a persistent ``ticketbox-data/``
folder via ``TICKETBOX_DATA_DIR``. These tests lock that wiring so a future
refactor can't silently send those writes back into the throwaway _MEIPASS
bundle (where they vanish on restart).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import app.config as config


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
