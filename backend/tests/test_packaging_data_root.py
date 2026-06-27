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


def test_build_log_config_routes_to_rotating_file(tmp_path):
    """uvicorn + app logs must land in a rotating file under the data dir, and the
    log dir must be created — the only diagnostics a windowed service has."""
    launch = _load_launch_module()
    log_dir = tmp_path / "logs"
    cfg = launch._build_log_config(log_dir, console=False)

    assert log_dir.is_dir()  # created as a side effect
    file_handler = cfg["handlers"]["file"]
    assert file_handler["class"] == "logging.handlers.RotatingFileHandler"
    assert file_handler["filename"] == str(log_dir / "backend.log")
    # root catches the app/middleware loggers; uvicorn loggers point at the file
    # and don't propagate (so they aren't double-logged via root).
    assert "file" in cfg["root"]["handlers"]
    assert cfg["loggers"]["uvicorn.error"]["handlers"] == cfg["root"]["handlers"]
    assert cfg["loggers"]["uvicorn.error"]["propagate"] is False


def test_build_log_config_omits_console_when_no_stdout(tmp_path):
    """console=False frozen build: sys.stdout/stderr are None — the config must
    attach NO stream handler, or uvicorn's first log line crashes on None.write."""
    launch = _load_launch_module()
    cfg = launch._build_log_config(tmp_path / "logs", console=False)

    assert set(cfg["handlers"]) == {"file"}
    for handler in cfg["handlers"].values():
        assert "stream" not in handler  # nothing references sys.stdout/stderr
    assert cfg["root"]["handlers"] == ["file"]


def test_build_log_config_keeps_console_when_stdout_present(tmp_path):
    """dev / console build keeps stdout output alongside the file."""
    launch = _load_launch_module()
    cfg = launch._build_log_config(tmp_path / "logs", console=True)

    assert "console" in cfg["handlers"]
    assert cfg["handlers"]["console"]["stream"] == "ext://sys.stdout"
    assert cfg["root"]["handlers"] == ["file", "console"]


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


def test_main_configures_file_logging_and_tells_uvicorn_not_to(monkeypatch, tmp_path):
    """main() must configure logging itself (dictConfig with the rotating file
    handler) AND pass log_config=None to uvicorn. If it dropped log_config=None,
    uvicorn would re-apply its default config (which streams to ext://sys.stdout)
    and crash on None.write under the windowed console=False build."""
    import logging.config

    import uvicorn

    launch = _load_launch_module()
    captured: dict = {}
    monkeypatch.setattr(launch, "configure_environment", lambda: tmp_path)
    monkeypatch.setattr(logging.config, "dictConfig", lambda cfg: captured.__setitem__("dictconfig", cfg))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.__setitem__("run_kwargs", kwargs))

    launch.main()

    assert captured["dictconfig"]["handlers"]["file"]["filename"] == str(tmp_path / "logs" / "backend.log")
    assert captured["run_kwargs"]["log_config"] is None


def test_alembic_env_skips_fileconfig_when_logging_already_configured():
    """ADR-0047 §8 guard (migrations/env.py): when a host has already configured
    logging (root has handlers — the launcher's dictConfig, or pytest), Alembic
    must NOT run fileConfig. fileConfig's default disable_existing_loggers=True +
    alembic.ini's stderr handler would tear down the launcher's rotating file
    handler, so the windowed console=False service loses every log line after its
    first startup migration. A sentinel handler installed on root must survive a
    command.upgrade (which loads env.py); it would be removed if env.py
    reconfigured logging — exactly the regression this guard prevents."""
    import logging

    from alembic import command
    from alembic.config import Config

    from app.config import BACKEND_ROOT
    from app.database import engine

    sentinel = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(sentinel)
    try:
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")  # no-op at head, but loads env.py and runs the guard
        assert sentinel in root.handlers, (
            "env.py ran fileConfig despite pre-existing handlers and tore down host logging"
        )
    finally:
        root.removeHandler(sentinel)
