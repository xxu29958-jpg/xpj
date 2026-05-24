"""baseline — v1.1 cut-over point.

Revision ID: 20260524_0001
Revises:
Create Date: 2026-05-24

This revision is a marker: it documents that the schema produced by
``Base.metadata.create_all`` + ``migrate_sqlite_schema`` at v1.1 is
the baseline going forward. Pre-existing databases are stamped to
this revision by :func:`app.database.init_db` so they don't replay
column additions Alembic doesn't know about.

New schema changes from v1.1 onward should be added as their own
revision files instead of extending the legacy idempotent migrator.
"""
from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260524_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Intentionally empty: the legacy boot path (Base.metadata.create_all
    # + migrate_sqlite_schema) materialises the v1.1 schema. This
    # revision just marks "we are at v1.1 baseline".
    pass


def downgrade() -> None:
    # No-op: the v1.1 baseline is the floor; downgrading past it is not
    # supported because we'd lose tenant_id / identity-schema columns
    # that the application now requires.
    raise NotImplementedError("Baseline revision has no downgrade")
