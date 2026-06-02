"""add hard expiry for upload links.

Revision ID: 20260528_0001
Revises: 9d8a7c6b5e4f
Create Date: 2026-05-28
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0001"
down_revision: str | Sequence[str] | None = "9d8a7c6b5e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_upload_links_expires_at"


def _upload_link_ttl_days() -> int:
    try:
        return max(1, int(os.getenv("UPLOAD_LINK_TTL_DAYS", "90")))
    except ValueError:
        return 90


def _legacy_expiry_spread_days() -> int:
    try:
        return max(1, int(os.getenv("UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS", "30")))
    except ValueError:
        return 30


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "upload_links"):
        return

    if "expires_at" not in _columns(bind, "upload_links"):
        with op.batch_alter_table("upload_links") as batch_op:
            batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # ``datetime('now', ...)`` is SQLite-only — PostgreSQL has no datetime()
    # function and rejects the statement at parse time even when zero rows
    # match. Branch on dialect (ADR-0041): SQLite keeps the original in-engine
    # expression; PostgreSQL builds the same ``now + (ttl + id-spread) days``
    # as a portable interval. The legacy backfill only has rows to touch on an
    # upgraded SQLite DB; on a fresh Postgres schema it is a no-op, but it must
    # still parse on the dual-dialect Alembic replay path.
    if bind.dialect.name == "sqlite":
        expiry_sql = (
            "UPDATE upload_links "
            "SET expires_at = datetime("
            "'now', "
            "'+' || :ttl_days || ' days', "
            "'+' || (ABS(id) % :spread_days) || ' days'"
            ") "
            "WHERE expires_at IS NULL"
        )
    else:
        expiry_sql = (
            "UPDATE upload_links "
            "SET expires_at = now() "
            "+ ((:ttl_days + (ABS(id) % :spread_days)) * INTERVAL '1 day') "
            "WHERE expires_at IS NULL"
        )
    bind.execute(
        sa.text(expiry_sql),
        {
            "ttl_days": _upload_link_ttl_days(),
            "spread_days": _legacy_expiry_spread_days(),
        },
    )
    if not _has_index(bind, "upload_links", INDEX_NAME):
        op.create_index(INDEX_NAME, "upload_links", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "upload_links"):
        return
    if _has_index(bind, "upload_links", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="upload_links")
    if "expires_at" in _columns(bind, "upload_links"):
        with op.batch_alter_table("upload_links") as batch_op:
            batch_op.drop_column("expires_at")
