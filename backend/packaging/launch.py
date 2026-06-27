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

Run (frozen):   double-click ticketbox-backend.exe
Run (dev):      python packaging/launch.py            (cwd = backend/)
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


def main() -> None:
    data_dir = configure_environment()
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
    # raise before uvicorn ever starts. Guard so the same entrypoint is safe in
    # both the current console build and the future windowed-service build.
    if sys.stdout is not None:
        print(f"Ticketbox backend  ·  data: {data_dir}  ·  http://{host}:{port}", flush=True)

    # ADR-0047 §1: when run as a Windows service, Shawl stops the process by
    # sending Ctrl-C (uvicorn → SIGINT → clean lifespan shutdown). Bound the
    # graceful drain so a stuck request can't hang service stop forever; Shawl's
    # --stop-timeout should be set >= this so it doesn't hard-kill first.
    shutdown_timeout = int(os.getenv("TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS", "25"))
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
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
