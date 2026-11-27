"""Frozen-EXE entry point for the Ticketbox backend.

PyInstaller bundles the read-only program (the ``app`` package, static assets,
Jinja templates, ``alembic.ini`` and ``migrations/``). The formal Windows
service receives the explicit ``TICKETBOX_DATA_DIR`` contract. The installed
instance binding or active fresh-install operation must match that path and
the exact immutable release. Only source/development invocation falls back to
``ticketbox-data/`` beside the program root. The database itself runs in the
installer-managed local PostgreSQL service. We set the data root BEFORE
importing ``app.*`` because :mod:`app.config` otherwise resolves paths against
PyInstaller's throwaway ``sys._MEIPASS`` extraction dir.

Run (frozen):   through the installer-validated Windows service contract
Run (dev):      python packaging/launch.py            (cwd = backend/)

The frozen build is windowed (``console=False``, ADR-0047 §8), so a running
service has no stdout/stderr. ``main()`` configures logging to a rotating file
under ``<data>/logs/`` BEFORE importing the app and tells uvicorn not to re-point
its handlers at ``sys.stdout`` — see :func:`_build_log_config`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, TextIO

if not getattr(sys, "frozen", False):
    source_backend_root = str(Path(__file__).resolve().parents[1])
    if source_backend_root not in sys.path:
        sys.path.insert(0, source_backend_root)
    source_packaging_root = str(Path(__file__).resolve().parent)
    if source_packaging_root not in sys.path:
        sys.path.insert(0, source_packaging_root)

from _database_maintenance_cli import (
    COLD_RESTORE_SWITCH as _COLD_RESTORE_SWITCH,
)
from _database_maintenance_cli import (
    DATABASE_GENERATION_TARGET_VERIFY_SWITCH as _DATABASE_GENERATION_TARGET_VERIFY_SWITCH,
)
from _database_maintenance_cli import (
    EXISTING_DATASET_UPGRADE_RESULT_FIELDS as _EXISTING_DATASET_UPGRADE_RESULT_FIELDS,
)
from _database_maintenance_cli import (
    EXISTING_DATASET_UPGRADE_SWITCH as _EXISTING_DATASET_UPGRADE_SWITCH,
)
from _database_maintenance_cli import (
    FRESH_OWNER_CLAIM_SWITCH as _FRESH_OWNER_CLAIM_SWITCH,
)
from _database_maintenance_cli import (
    FRESH_OWNER_RESULT_FIELDS as _FRESH_OWNER_RESULT_FIELDS,
)
from _database_maintenance_cli import (
    FRESH_SCHEMA_RESULT_FIELDS as _FRESH_SCHEMA_RESULT_FIELDS,
)
from _database_maintenance_cli import (
    FRESH_SCHEMA_UPGRADE_SWITCH as _FRESH_SCHEMA_UPGRADE_SWITCH,
)
from _database_maintenance_cli import (
    GENERATION_PROGRAM_VALIDATE_SWITCH as _GENERATION_PROGRAM_VALIDATE_SWITCH,
)
from _database_maintenance_cli import (
    GENERATION_PROGRAM_VALIDATION_FIELDS as _GENERATION_PROGRAM_VALIDATION_FIELDS,
)
from _database_maintenance_cli import (
    VERIFY_PRESERVED_DATASET_SWITCH as _VERIFY_PRESERVED_DATASET_SWITCH,
)
from _database_maintenance_cli import (
    parse_database_generation_target_args as _parse_database_generation_target_args,
)
from _database_maintenance_cli import (
    parse_existing_dataset_upgrade_args as _parse_existing_dataset_upgrade_args,
)
from _database_maintenance_cli import (
    parse_fresh_owner_claim_args as _parse_fresh_owner_claim_args,
)
from _database_maintenance_cli import (
    parse_fresh_schema_upgrade_args as _parse_fresh_schema_upgrade_args,
)
from _database_maintenance_cli import (
    parse_generation_program_validation_args as _parse_generation_program_validation_args,
)
from _database_maintenance_cli import (
    run_database_generation_target_verification as _exec_database_generation_target_verification,
)
from _database_maintenance_cli import (
    run_existing_dataset_upgrade as _exec_existing_dataset_upgrade,
)
from _database_maintenance_cli import (
    run_fresh_owner_claim as _exec_fresh_owner_claim,
)
from _database_maintenance_cli import (
    run_fresh_schema_upgrade as _exec_fresh_schema_upgrade,
)
from _database_maintenance_cli import (
    run_generation_program_validation as _exec_generation_program_validation,
)
from _runtime_authority_contract import (
    _FROZEN_HOST_AUTHORITY_KEYS,
    _RELEASE_ID_PATTERN,
    _closed_authorities,
)
from _runtime_authority_contract import (
    assert_runtime_data_root_authority as _assert_runtime_data_root_authority,
)
from _runtime_authority_contract import (
    assert_vnext_runtime_authority as _assert_vnext_runtime_authority,
)

from app.database_maintenance_runtime import (
    assert_maintenance_libpq_environment as _assert_maintenance_libpq_environment,
)
from app.database_maintenance_runtime import (
    load_standalone_database_module as _load_standalone_database_module,
)
from app.database_maintenance_runtime import (
    resolve_generation_program as _resolve_generation_program,
)

_HEALTH_ATTESTATION_ENV = "TICKETBOX_HEALTH_ATTESTATION_KEY"
_RESTORE_ENV_KEYS = (
    "TICKETBOX_EXPECTED_RESTORE_EPOCH",
    "TICKETBOX_RESTORE_VERIFY_ONLY",
    "TICKETBOX_UPGRADE_VERIFY_ONLY",
    "TICKETBOX_RELEASE_MANIFEST_SHA256",
)
_DATABASE_GENERATION_HELPER_NAME = "ticketbox-database-maintenance.exe"
_GENERATION_PROGRAM_VALIDATION_MODULE_NAME = "_ticketbox_database_generation_program_validation"
_FRESH_SCHEMA_MODULE_NAME = "_ticketbox_fresh_schema_upgrade"
_EXISTING_DATASET_UPGRADE_MODULE_NAME = "_ticketbox_existing_dataset_upgrade"
_DATABASE_GENERATION_TARGET_MODULE_NAME = "_ticketbox_database_generation_target"


def _bundle_dir() -> Path:
    """Directory the EXE was launched from (read-only program root when frozen).

    Frozen: the folder the user dropped the EXE in (``sys.executable``). Used
    ONLY to locate the *default* writable folder — never to write into when an
    installer/service has pre-set ``TICKETBOX_DATA_DIR`` (the EXE may sit in a
    read-only ``Program Files``). Dev: the backend/ project root (two levels up).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _is_database_generation_helper() -> bool:
    return getattr(sys, "frozen", False) and Path(sys.executable).name.lower() == _DATABASE_GENERATION_HELPER_NAME


def _load_generation_program_validation_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_GENERATION_PROGRAM_VALIDATION_MODULE_NAME,
        filename="_database_generation_program_validation.py",
        database_package_seam=True,
    )


def _load_fresh_schema_upgrade_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_FRESH_SCHEMA_MODULE_NAME,
        filename="_fresh_schema_upgrade.py",
        database_package_seam=True,
    )


def _load_existing_dataset_upgrade_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_EXISTING_DATASET_UPGRADE_MODULE_NAME,
        filename="_existing_dataset_upgrade.py",
        database_package_seam=True,
    )


def _load_database_generation_target_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_DATABASE_GENERATION_TARGET_MODULE_NAME,
        filename="_database_generation_target_verification.py",
        database_package_seam=True,
    )


def _run_generation_program_validation(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    return _exec_generation_program_validation(
        argv,
        load_module=_load_generation_program_validation_module,
        resolve_program=_resolve_generation_program,
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _run_fresh_schema_upgrade(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    return _exec_fresh_schema_upgrade(
        argv,
        assert_libpq=_assert_maintenance_libpq_environment,
        load_module=_load_fresh_schema_upgrade_module,
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _run_existing_dataset_upgrade(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    return _exec_existing_dataset_upgrade(
        argv,
        assert_libpq=_assert_maintenance_libpq_environment,
        load_module=_load_existing_dataset_upgrade_module,
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _run_fresh_owner_claim(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    return _exec_fresh_owner_claim(
        argv,
        assert_libpq=_assert_maintenance_libpq_environment,
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _run_database_generation_target_verification(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    return _exec_database_generation_target_verification(
        argv,
        assert_libpq=_assert_maintenance_libpq_environment,
        load_module=_load_database_generation_target_module,
        resolve_program=_resolve_generation_program,
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _resolve_writable_data_dir() -> Path:
    """Writable data root for backend uploads and operator configuration.

    Honors the explicit installer/service ``TICKETBOX_DATA_DIR``. Frozen
    service startup additionally verifies this path against the installed
    instance binding or the active fresh-install operation. Only source mode
    may fall back to a ``ticketbox-data/`` folder beside the program root.
    """
    preset = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    if preset:
        return Path(os.path.abspath(preset))
    return _bundle_dir() / "ticketbox-data"


def configure_environment() -> Path:
    """Point the app at a writable data dir; return that dir.

    Installed frozen builds require the complete host authority injected by the
    validated service contract. Source mode may omit that contract and resolve a
    local writable directory. A user-supplied ``<data>/.env`` then wins for the
    business/runtime values it sets (override=True), but never for host authority.
    ``DATABASE_URL`` is not defaulted here because PostgreSQL remains authoritative.
    """
    data_dir = _resolve_writable_data_dir()
    # These values are supplied by the host/service contract. The writable
    # app .env may configure business settings but cannot replace host identity.
    host_authority = {key: os.environ.get(key) for key in _FROZEN_HOST_AUTHORITY_KEYS}
    os.environ.pop(_HEALTH_ATTESTATION_ENV, None)
    for key in _RESTORE_ENV_KEYS:
        os.environ.pop(key, None)
    health_attestation_key = _assert_runtime_data_root_authority(data_dir)
    restore_authority = {key: os.environ.get(key) for key in _RESTORE_ENV_KEYS}
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    # Anchor app.config.DATA_ROOT here so mutable application data
    # (Owner Console settings .env and uploaded attachments) persists here
    # rather than the frozen build's throwaway _MEIPASS extraction dir. We
    # normalize the (possibly preset) value before the .env load and before
    # main() imports app.* so app.config reads the same resolved path we just
    # mkdir'd. This assignment is now idempotent with a preset (data_dir == the
    # resolved preset), so it normalizes rather than clobbering a service path.
    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)

    env_file = data_dir / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, encoding="utf-8-sig", override=True)

    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)
    for key, value in host_authority.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    for key, value in restore_authority.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if health_attestation_key is None:
        os.environ.pop(_HEALTH_ATTESTATION_ENV, None)
    else:
        os.environ[_HEALTH_ATTESTATION_ENV] = health_attestation_key

    # DATABASE_URL is intentionally not defaulted: the backend is PostgreSQL-only.
    # A user .env may set it; otherwise app.config supplies the local-PostgreSQL
    # default (the EXE assumes a local PostgreSQL service is installed).
    os.environ.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    return data_dir


def _build_log_config(log_dir: Path, *, console: bool | None = None) -> dict:
    """Build a ``logging.config.dictConfig`` for the frozen backend.

    Everything — uvicorn's loggers plus the app/middleware loggers via the root
    logger — goes to a size-bounded rotating file under the writable data dir.
    This is what makes the windowed ``console=False`` service build (ADR-0047 §8)
    viable: there ``sys.stdout``/``sys.stderr`` are ``None``, so uvicorn's default
    config (which streams to ``ext://sys.stdout``) and Python's lastResort stderr
    handler would both crash on ``None.write`` — and a service with no console
    would die with no diagnostics. Routing to a file gives the service real logs.

    When a usable console exists (dev / source run) logs also echo to stdout.
    ``console`` defaults to whether ``sys.stdout`` is a real stream; tests pass it
    explicitly to exercise both shapes without mutating the global stream.
    """
    if console is None:
        console = sys.stdout is not None
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: dict[str, dict] = {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_dir / "backend.log"),
            # Bounded so a long-running self-hosted service can't grow logs
            # without limit (ENGINEERING_RULES §12): ~5 MB × 3 backups.
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "plain",
            "level": "INFO",
        }
    }
    active = ["file"]
    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "plain",
            "level": "INFO",
        }
        active.append("console")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {"()": "app.log_sanitize.SanitizedFormatter"},
        },
        "handlers": handlers,
        # Root catches the app + middleware loggers (they have no own handlers).
        "root": {"handlers": active, "level": "INFO"},
        "loggers": {
            # uvicorn ships its own handlers; repoint them at ours and stop
            # propagation so its lines aren't also re-emitted via the root logger.
            "uvicorn": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": active, "level": "INFO", "propagate": False},
        },
    }


def _initialize_installed_runtime_settings(data_dir: Path) -> None:
    """Create the service-owned initial projection before importing the app."""

    from app.services.runtime_settings_store import (
        RuntimeSettingsProjection,
        initialize_runtime_settings,
    )

    settings_dir = data_dir / "runtime-settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    initialize_runtime_settings(
        settings_dir / "runtime-settings.json",
        RuntimeSettingsProjection("", False),
        service_owned=True,
    )


def _run_cold_restore_mode(arguments: list[str]) -> int:
    from app.cold_restore_runtime import run_cold_restore

    return run_cold_restore(arguments)


def _run_verify_preserved_dataset_mode(arguments: list[str]) -> int:
    from app.cold_restore_runtime import run_verify_preserved_dataset

    return run_verify_preserved_dataset(arguments)


def _dispatch_maintenance_mode(arguments: list[str]) -> int | None:
    handlers = (
        (_FRESH_SCHEMA_UPGRADE_SWITCH, _run_fresh_schema_upgrade),
        (_EXISTING_DATASET_UPGRADE_SWITCH, _run_existing_dataset_upgrade),
        (_FRESH_OWNER_CLAIM_SWITCH, _run_fresh_owner_claim),
        (_COLD_RESTORE_SWITCH, _run_cold_restore_mode),
        (_VERIFY_PRESERVED_DATASET_SWITCH, _run_verify_preserved_dataset_mode),
        (_DATABASE_GENERATION_TARGET_VERIFY_SWITCH, _run_database_generation_target_verification),
        (_GENERATION_PROGRAM_VALIDATE_SWITCH, _run_generation_program_validation),
    )
    matched = [handler for switch, handler in handlers if switch in arguments]
    if len(matched) > 1:
        raise RuntimeError("database generation helper accepts exactly one mode")
    if not matched:
        return None
    if getattr(sys, "frozen", False) and not _is_database_generation_helper():
        raise RuntimeError("database generation requires the dedicated frozen helper")
    return matched[0](arguments)


def main() -> int | None:
    arguments = sys.argv[1:]
    maintenance_rc = _dispatch_maintenance_mode(arguments)
    if maintenance_rc is not None:
        return maintenance_rc
    if _is_database_generation_helper():
        raise RuntimeError("the dedicated database generation helper requires an explicit mode")

    import logging.config

    data_dir = configure_environment()
    # Configure logging to a rotating file under the data dir BEFORE importing the
    # app, so the console=False service build (sys.stdout/stderr None) never falls
    # through to logging's lastResort stderr handler, and startup/import-time
    # diagnostics are captured. See _build_log_config + ADR-0047 §8.
    logging.raiseExceptions = False
    logging.config.dictConfig(_build_log_config(data_dir / "logs"))
    if getattr(sys, "frozen", False):
        _initialize_installed_runtime_settings(data_dir)
    host = os.getenv("TICKETBOX_HOST", "127.0.0.1")
    port = int(os.getenv("TICKETBOX_PORT", "8000"))

    # Import the app object directly (not the "app.main:app" string form):
    # uvicorn's string import re-resolves the module via importlib, which is
    # unreliable in a frozen bundle and masks real import errors as
    # "Could not import module". Passing the object also makes any failure in
    # the app's import graph surface here with a real traceback.
    import uvicorn

    from app.main import app as fastapi_app

    # console=False (ADR-0047 §8 service build) gives a windowed PyInstaller
    # process no stdout/stderr — ``sys.stdout`` is None and ``.write`` would
    # raise. Guard so the same entrypoint is safe in both the console build and
    # the windowed-service build (the file log records startup either way).
    if sys.stdout is not None:
        print(f"Ticketbox backend  ·  data: {data_dir}  ·  http://{host}:{port}", flush=True)

    # ADR-0047 §Confirmation: keep a bounded drain for service builds. Slice 2-D
    # verified the current console=False Shawl service build does not receive
    # Ctrl-C/SIGINT and falls back to Shawl's stop-timeout kill; the app writes
    # no business state during lifespan shutdown, while PG keeps durability.
    shutdown_timeout = int(os.getenv("TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS", "25"))
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        # Logging is already configured above (file + optional console). Pass
        # None so uvicorn does NOT re-apply its default config, which streams to
        # ext://sys.stdout and would crash under console=False.
        log_config=None,
        timeout_graceful_shutdown=shutdown_timeout,
    )


__all__ = [
    "_EXISTING_DATASET_UPGRADE_RESULT_FIELDS",
    "_FRESH_OWNER_RESULT_FIELDS",
    "_FRESH_SCHEMA_RESULT_FIELDS",
    "_GENERATION_PROGRAM_VALIDATION_FIELDS",
    "_RELEASE_ID_PATTERN",
    "_assert_vnext_runtime_authority",
    "_closed_authorities",
    "_parse_database_generation_target_args",
    "_parse_existing_dataset_upgrade_args",
    "_parse_fresh_owner_claim_args",
    "_parse_fresh_schema_upgrade_args",
    "_parse_generation_program_validation_args",
    "configure_environment",
    "main",
]


if __name__ == "__main__":
    import multiprocessing

    # PyInstaller hardening (ADR-0047 §8): a frozen build that ever spawns a
    # child process (e.g. a future multi-worker uvicorn) would otherwise
    # re-execute the bootloader and recursively launch the app. No-op today
    # (workers=1, app object passed directly), required before any spawn lands.
    multiprocessing.freeze_support()
    exit_code = main()
    if exit_code is not None:
        raise SystemExit(exit_code)
