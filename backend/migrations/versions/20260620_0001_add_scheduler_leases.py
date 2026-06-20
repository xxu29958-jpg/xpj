"""add scheduler_leases (typed timestamptz scheduler coordination lease).

Revision ID: 20260620_0001
Revises: 20260619_0001
Create Date: 2026-06-20

docs/audits/2026-06-14-known-bugs.md 🟢#4: the scheduler lease used to live in the
generic ``app_meta`` KV table with the expiry stored as a UTC-ISO **string** and
compared lexicographically. This replaces it with a dedicated ``scheduler_leases``
table whose ``expires_at`` is a real ``timestamptz`` (the claim now compares times
by type, and the whole claim is a single atomic ``INSERT ... ON CONFLICT DO UPDATE
... WHERE expires_at <= now() RETURNING name``).

The ORM declares the model, so a fresh ``Base.metadata.create_all`` (the bridge
``init_db()`` runs before ``alembic upgrade head``) already has the table — the
``create_table`` is guarded so the revision stays a no-op there, same shape as
20260616_0001. On the pure-Alembic (existing-DB upgrade) path this creates the
table to match ``create_all``.

It also drops the transient ``app_meta`` lease rows (``scheduler_lease:<name>``)
so ``app_meta`` returns to its schema/version/secret keys. That DELETE is a no-op
on the fresh path (no such rows) and one-way (the rows are throwaway coordination
state, never restored). ``downgrade()`` drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260620_0001"
down_revision: str | Sequence[str] | None = "20260619_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# len("scheduler_lease:") — exact-prefix match avoids LIKE's ``_`` wildcard
# matching anything other than the literal underscore in the old key prefix.
_LEGACY_LEASE_KEY_PREFIX = "scheduler_lease:"


def _create_scheduler_leases() -> None:
    op.create_table(
        "scheduler_leases",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "scheduler_leases" not in existing:
        _create_scheduler_leases()
    # Drop the transient pre-table lease rows from app_meta. Exact prefix match
    # (substr == prefix) — never matches schema_version / *_compatible / learning
    # cleanup keys. No-op on a fresh create_all'd DB (no such rows exist yet).
    op.execute(
        sa.text(
            "DELETE FROM app_meta "
            "WHERE substr(key, 1, :prefix_len) = :prefix"
        ).bindparams(
            prefix_len=len(_LEGACY_LEASE_KEY_PREFIX),
            prefix=_LEGACY_LEASE_KEY_PREFIX,
        )
    )


def downgrade() -> None:
    op.drop_table("scheduler_leases")
