"""Managed-host and source/development data-root contract.

When the backend runs as a PyInstaller one-file EXE, ``BACKEND_ROOT`` is the
throwaway ``_MEIPASS`` extraction dir. Files the backend *writes* — the Owner
Console settings ``.env`` and PostgreSQL backups — must instead live under
``DATA_ROOT``. The formal Windows service receives the machine-owned
``TicketboxRuntimeBinding/data-root/app`` junction through
``TICKETBOX_DATA_DIR``; its v2 marker and Volume GUID bind the physical
``<DataRoot>/app`` bytes. Only source/development runs may use the adjacent
``ticketbox-data/`` fallback. These tests prevent writes into ``_MEIPASS``.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_resolve_data_root_anchors_relative_override_to_backend_root(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    monkeypatch.setenv("TICKETBOX_DATA_DIR", "runtime-data")
    monkeypatch.chdir(tmp_path.parent)

    assert config._resolve_data_root(backend_root) == (backend_root / "runtime-data").resolve()


def test_resolve_data_root_ignores_blank_env(monkeypatch):
    monkeypatch.setenv("TICKETBOX_DATA_DIR", "   ")
    backend_root = Path("/srv/ticketbox/backend")
    assert config._resolve_data_root(backend_root) == backend_root


@pytest.mark.parametrize("channel", ["development", "managed_host", "operator"])
def test_owner_recovery_channel_accepts_only_declared_deployment_capabilities(
    monkeypatch,
    channel,
):
    monkeypatch.setenv("TICKETBOX_OWNER_RECOVERY_CHANNEL", channel.upper())

    assert config._choice_env(
        "TICKETBOX_OWNER_RECOVERY_CHANNEL",
        "development",
        config.OWNER_RECOVERY_CHANNELS,
    ) == channel


def test_owner_recovery_channel_rejects_undeclared_host_guess(monkeypatch):
    monkeypatch.setenv("TICKETBOX_OWNER_RECOVERY_CHANNEL", "frozen_windows")

    with pytest.raises(ValueError, match="TICKETBOX_OWNER_RECOVERY_CHANNEL must be one of"):
        config._choice_env(
            "TICKETBOX_OWNER_RECOVERY_CHANNEL",
            "development",
            config.OWNER_RECOVERY_CHANNELS,
        )


def test_launcher_honors_preset_data_dir(monkeypatch, tmp_path):
    """An installer/service-preset TICKETBOX_DATA_DIR (e.g. C:\\ProgramData\\...)
    must WIN. The launcher must not recompute the EXE-adjacent default and clobber
    it, or the ADR-0047 service can't run from a read-only Program Files install
    with its data in ProgramData."""
    launch = _load_launch_module()
    preset = tmp_path / "ProgramData" / "TicketboxRuntimeBinding" / "data-root" / "app"
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    assert launch._resolve_writable_data_dir() == preset.resolve()


def test_launcher_defaults_next_to_bundle_when_unset(monkeypatch):
    """Source/development runs default to ticketbox-data beside the program root."""
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

    Simulates a managed host where DATA_ROOT diverges from the read-only program
    root. Reloads the leaf service modules so their module-level path constants
    recompute against the redirected DATA_ROOT, then restores the real value so
    no other test is affected.
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
    validated_junction = tmp_path / "validated-runtime-junction"
    monkeypatch.setattr(launch, "configure_environment", lambda: tmp_path)
    monkeypatch.setattr(
        launch,
        "_assert_runtime_data_root_authority",
        lambda data_dir: validated_junction,
    )
    monkeypatch.setattr(
        launch,
        "_assert_bootstrap_recovery_not_pending",
        lambda runtime_junction: captured.__setitem__(
            "validated_runtime_junction",
            runtime_junction,
        ),
    )
    monkeypatch.setattr(logging.config, "dictConfig", lambda cfg: captured.__setitem__("dictconfig", cfg))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.__setitem__("run_kwargs", kwargs))

    launch.main()

    assert captured["dictconfig"]["handlers"]["file"]["filename"] == str(tmp_path / "logs" / "backend.log")
    assert captured["run_kwargs"]["log_config"] is None
    assert captured["validated_runtime_junction"] == validated_junction


def test_main_refuses_http_startup_while_bootstrap_recovery_is_pending(
    monkeypatch, tmp_path
):
    from app.services.identity_service import ReplacementCredentialCollisionError

    launch = _load_launch_module()
    assert (
        launch._maintenance_error_code(ReplacementCredentialCollisionError())
        == "replacement_credential_collision"
    )
    guard = tmp_path / "bootstrap-recovery-pending"
    guard.write_text("STATE=pending\n", encoding="utf-8")
    monkeypatch.setenv("TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH", str(guard))
    monkeypatch.setattr(launch, "configure_environment", lambda: tmp_path)

    with pytest.raises(RuntimeError, match="bootstrap credential recovery is pending"):
        launch.main()


def _run_guarded_request(launch, guard_path: Path, path: str) -> tuple[list[dict], list[dict]]:
    messages: list[dict] = []
    downstream_scopes: list[dict] = []

    async def downstream(scope, receive, send):
        downstream_scopes.append(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    guarded = launch._InstallerRuntimeRecoveryGuard(downstream, guard_path)
    asyncio.run(
        guarded(
            {"type": "http", "method": "GET", "path": path, "headers": []},
            receive,
            send,
        )
    )
    return messages, downstream_scopes


def test_installer_runtime_guard_blocks_normal_http_until_removed(tmp_path):
    launch = _load_launch_module()
    guard = tmp_path / "installer-runtime-recovery-pending"
    guard.write_text("pending", encoding="utf-8")

    blocked, blocked_downstream = _run_guarded_request(launch, guard, "/api/expenses")
    assert blocked[0]["status"] == 503
    assert json.loads(blocked[1]["body"])["error"] == "installer_recovery_pending"
    assert blocked_downstream == []

    guard.unlink()
    allowed, allowed_downstream = _run_guarded_request(launch, guard, "/api/expenses")
    assert allowed[0]["status"] == 204
    assert [scope["path"] for scope in allowed_downstream] == ["/api/expenses"]
    assert "ticketbox_runtime_access_state" not in allowed_downstream[0].get("state", {})

    class DanglingReparseParent:
        parent = None

        def lstat(self):
            return SimpleNamespace(
                st_mode=stat.S_IFLNK,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )

    dangling_parent = DanglingReparseParent()
    dangling_parent.parent = dangling_parent

    class MissingLeafBelowReparse:
        parent = dangling_parent

        def lstat(self):
            raise FileNotFoundError("dangling runtime-state reparse target")

    malformed, malformed_downstream = _run_guarded_request(
        launch,
        MissingLeafBelowReparse(),
        "/api/expenses",
    )
    assert malformed[0]["status"] == 503
    assert malformed_downstream == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/health/installation",
        "/api/bootstrap/installation-owner",
        "/api/bootstrap/owner",
    ],
)
def test_installer_runtime_guard_allows_only_repair_endpoints(tmp_path, path):
    from app.services.installation_health_service import installation_runtime_access_state

    launch = _load_launch_module()
    guard = tmp_path / "installer-runtime-recovery-pending"
    guard.write_text("pending", encoding="utf-8")

    messages, downstream_paths = _run_guarded_request(launch, guard, path)

    assert messages[0]["status"] == 204
    assert [scope["path"] for scope in downstream_paths] == [path]
    assert downstream_paths[0]["state"]["ticketbox_runtime_access_state"] == "repair_required"
    assert installation_runtime_access_state(downstream_paths[0]) == "repair_required"


def test_installer_runtime_guard_fails_closed_when_status_cannot_be_read():
    launch = _load_launch_module()

    class UnreadableGuard:
        def lstat(self):
            raise PermissionError("denied")

    assert launch._installer_runtime_recovery_is_pending(UnreadableGuard()) is True


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

    backend_root = Path(__file__).resolve().parents[1]
    cli_probe = """
import sys
sys.path.insert(0, sys.argv[1])
from alembic import command
from alembic.config import Config

config = Config(sys.argv[1] + "/alembic.ini")
config.set_main_option("script_location", sys.argv[1] + "/migrations")
command.current(config)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            cli_probe,
            str(backend_root),
        ],
        cwd=backend_root,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "[alembic.runtime.migration]" in completed.stderr
