"""Materialize the frozen PostgreSQL v1.1 baseline.

Revision ID: 20260524_0001
Revises:
Create Date: 2026-05-24

The DDL was compiled from the real model tree at commit ``31691ab4``, where
this revision first entered the graph. It is static on purpose: fresh
PostgreSQL databases are created only by ``alembic upgrade head`` and never
from the running binary's current ORM shape.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.versions._baseline import STATEMENT_GROUPS

# revision identifiers, used by Alembic.
revision: str = "20260524_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(
        bind.scalars(
            sa.text(
                "SELECT c.relname FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
            )
        )
    ) - {"alembic_version"}
    if existing:
        sample = ", ".join(sorted(existing)[:8])
        raise RuntimeError(
            "20260524_0001 only bootstraps an empty PostgreSQL schema; "
            f"found existing tables: {sample}"
        )
    for statements in STATEMENT_GROUPS:
        for statement in statements:
            op.execute(statement)
    op.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES "
        "('schema_version', '1.0.0', CURRENT_TIMESTAMP), "
        "('schema_min_compatible', '1.0.0', CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    raise NotImplementedError("Baseline revision has no downgrade")
