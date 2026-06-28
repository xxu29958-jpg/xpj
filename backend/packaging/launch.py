"""Frozen-EXE entry point for the Ticketbox backend.

PyInstaller bundles the read-only program (the ``app`` package, static assets,
Jinja templates, ``alembic.ini`` and ``migrations/``). Everything the running
backend *writes* — uploaded images, ``.env`` overrides, logs, and PostgreSQL
backups — lives in a separate, writable ``ticketbox-data/`` folder next to the
EXE. The database itself runs in a local PostgreSQL service (see
docs/runbook/POSTGRES_MIGRATION.md), not in this folder. We point the app's
config there via env vars BEFORE importing ``app.*``, because :mod:`app.config`
resolves paths relative to its own location, which in a frozen build is the
throwaway extraction dir (``sys._MEIPASS``).

Run (frozen):   double-click ticketbox-backend/ticketbox-backend.exe (onedir folder)
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


def _resolve_writable_data_dir() -> Path:
    """Writable data root for files the backend *creates* (uploads, .env, backups).

    Honors an installer/service-preset ``TICKETBOX_DATA_DIR`` — the ADR-0047
    service deployment points it at ``C:\\ProgramData\\Ticketbox\\app`` because the
    onedir EXE lives in a read-only/locked location. Only when it is unset/blank
    do we fall back to a ``ticketbox-data/`` folder next to the EXE (dev / the
    single-folder 档 A install). Resolving a preset HERE — instead of computing
    the EXE-adjacent default and unconditionally overwriting the preset later —
    is what lets the service run from a read-only ``Program Files`` install.
    """
    preset = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    if preset:
        return Path(preset).resolve()
    return _bundle_dir() / "ticketbox-data"


def configure_environment() -> Path:
    """Point the app at a writable data dir; return that dir.

    A preset ``TICKETBOX_DATA_DIR`` (installer / service) wins; otherwise data
    lives next to the EXE. A user-supplied ``<data>/.env`` then wins for the
    values it sets (override=True). ``DATABASE_URL`` is NOT defaulted here — the
    backend is PostgreSQL-only, so it falls through to ``app.config``'s
    local-PostgreSQL default unless the ``.env`` sets it.
    """
    data_dir = _resolve_writable_data_dir()
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    # Anchor app.config.DATA_ROOT here so writable files the backend *creates*
    # (Owner Console settings .env, PostgreSQL backups) persist in this folder
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
            "plain": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
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


def main() -> None:
    import logging.config

    data_dir = configure_environment()
    host = os.getenv("TICKETBOX_HOST", "127.0.0.1")
    port = int(os.getenv("TICKETBOX_PORT", "8000"))

    # Configure logging to a rotating file under the data dir BEFORE importing the
    # app, so the console=False service build (sys.stdout/stderr None) never falls
    # through to logging's lastResort stderr handler, and startup/import-time
    # diagnostics are captured. See _build_log_config + ADR-0047 §8.
    logging.config.dictConfig(_build_log_config(data_dir / "logs"))

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


if __name__ == "__main__":
    import multiprocessing

    # PyInstaller hardening (ADR-0047 §8): a frozen build that ever spawns a
    # child process (e.g. a future multi-worker uvicorn) would otherwise
    # re-execute the bootloader and recursively launch the app. No-op today
    # (workers=1, app object passed directly), required before any spawn lands.
    multiprocessing.freeze_support()
    main()
