"""Alembic environment — wires app.database into the migration context.

Adopted v1.1 (Batch 3). The single source of truth for the database URL
is :func:`app.config.get_settings`, so this env.py never re-reads
alembic.ini's ``sqlalchemy.url`` placeholder.

The legacy idempotent migrator in :mod:`app.database._migrations`
remains the boot path for *existing* DBs (any column it adds is also
present in the SQLAlchemy models, so create_all is a no-op there). New
schema changes from v1.1 onward should ship as Alembic revisions.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the backend root importable when alembic is invoked from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Force app.models import so every table is attached to Base.metadata
# before Alembic compares against the database.
from app import models  # noqa: E402, F401
from app.config import get_settings  # noqa: E402
from app.database._core import Base  # noqa: E402

config = context.config
_C07_JSON_PROTOCOL_ATTRIBUTE = "ticketbox_c07_json_protocol_v1"
_MANAGED_MIGRATION_JSON_PROTOCOL_ATTRIBUTE = (
    "ticketbox_managed_migration_json_protocol_v1"
)


def _configure_c07_json_protocol_logging() -> None:
    """Keep Alembic diagnostics outside the helper's stdout/stderr protocol."""

    alembic_logger = logging.getLogger("alembic")
    if not any(
        isinstance(handler, logging.NullHandler)
        for handler in alembic_logger.handlers
    ):
        alembic_logger.addHandler(logging.NullHandler())
    alembic_logger.propagate = False


# ``alembic.ini`` intentionally routes the standalone CLI's progress messages
# to stderr.  The dedicated C07 helper instead owns a strict JSON stdout
# protocol whose Windows host rejects any stderr bytes.  Its Config opts into a
# versioned attribute, so this environment skips fileConfig and installs the
# standard no-op handler recommended for a logging namespace that must not fall
# through to Python's stderr ``lastResort`` handler.  Exceptions still escape
# normally and produce a non-zero helper exit.
if any(
    config.attributes.get(attribute) is True
    for attribute in (
        _C07_JSON_PROTOCOL_ATTRIBUTE,
        _MANAGED_MIGRATION_JSON_PROTOCOL_ATTRIBUTE,
    )
):
    _configure_c07_json_protocol_logging()
# Only let Alembic configure logging when it owns the process — i.e. the
# standalone ``alembic`` CLI, where nothing has set up logging yet. When
# migrations run programmatically (``command.upgrade`` from ``init_db`` at app
# startup) the host has already configured logging, and ``fileConfig``'s default
# ``disable_existing_loggers=True`` + alembic.ini's stderr handler would tear it
# down. In the windowed ``console=False`` frozen build (ADR-0047 §8) that
# replaces the launcher's rotating file handler with a dead stderr handler, so
# the service loses every log line after its first startup migration. Skipping
# fileConfig when handlers already exist preserves the source/CLI behavior
# (root has no handlers there) while keeping the frozen service's file logging.
elif config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Honor a DATABASE_URL override (test lane, ad-hoc cli runs) before
    # falling back to the application settings.
    return os.environ.get("DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        context.configure(
            connection=existing_connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        cfg, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
