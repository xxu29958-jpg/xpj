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

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the backend root importable when alembic is invoked from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.database._core import Base  # noqa: E402

# Force app.models import so every table is attached to Base.metadata
# before Alembic compares against the database.
from app import models  # noqa: E402, F401

config = context.config
if config.config_file_name is not None:
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
