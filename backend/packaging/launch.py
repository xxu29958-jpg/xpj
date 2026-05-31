"""Frozen-EXE entry point for the Ticketbox backend.

PyInstaller bundles the read-only program (the ``app`` package, static assets,
Jinja templates, ``alembic.ini`` and ``migrations/``). Everything the running
backend *writes* — the SQLite database, uploaded images, ``.env`` overrides,
logs — lives in a separate, writable ``ticketbox-data/`` folder next to the
EXE. We point the app's config there via env vars BEFORE importing ``app.*``,
because :mod:`app.config` resolves paths relative to its own location, which in
a frozen build is the throwaway extraction dir (``sys._MEIPASS``).

Run (frozen):   double-click ticketbox-backend.exe
Run (dev):      python packaging/launch.py            (cwd = backend/)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    """Directory that holds the writable data folder.

    Frozen: the folder the user dropped the EXE in (``sys.executable``).
    Dev:    the backend/ project root (two levels up from this file).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def configure_environment() -> Path:
    """Point the app at a writable data dir; return that dir.

    Order matters: a user-supplied ``ticketbox-data/.env`` wins (override=True),
    and the data-dir defaults only fill what the user did not set
    (``setdefault``). So an advanced user can repoint DATABASE_URL elsewhere
    while a friend who just double-clicks gets a self-contained folder.
    """
    data_dir = _app_root() / "ticketbox-data"
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    # Anchor app.config.DATA_ROOT here so writable files the backend *creates*
    # (Owner Console settings .env, SQLite backups) persist in this folder rather
    # than the frozen build's throwaway _MEIPASS extraction dir. Set before the
    # .env load and before main() imports app.* so app.config reads it.
    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)

    env_file = data_dir / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, encoding="utf-8-sig", override=True)

    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(data_dir / 'ticketbox.db').as_posix()}")
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

    print(f"Ticketbox backend  ·  data: {data_dir}  ·  http://{host}:{port}", flush=True)
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
