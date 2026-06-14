"""drop the debt fact tables' global idempotency_key unique constraints.

Revision ID: 20260614_0003
Revises: 20260614_0002
Create Date: 2026-06-14

ADR-0049 §3.6 idempotency-scope fix. Slice 1 (20260614_0001) gave
``repayments`` / ``debt_adjustments`` / ``repayment_voids`` / ``debt_voids`` a
*global* ``UNIQUE(idempotency_key)``. That scope is wrong: client-generated
keys are only unique per tenant — [[0042]]'s ``api_idempotency_keys`` already
enforces ``(tenant_id, idempotency_key)`` — so two ledgers legitimately reusing
the same key would collide on a fact table. The ORM models no longer declare
these constraints; this forward revision drops them on any DB that already
applied slice 1, rather than editing the merged 20260614_0001 in place (which
would leave already-migrated databases with the stale constraint).

``DROP CONSTRAINT IF EXISTS`` because the normal ``init_db`` path is
``create_all`` (from the current models, which never declare the constraint) +
``alembic stamp`` + ``upgrade head``; on that path 20260614_0001's guarded
``create_table`` is skipped, so the constraint was never created and the drop
must be a no-op rather than an error. On a pure-Alembic DB 20260614_0001 created
the constraint and this drops it.

``downgrade`` re-adds the constraints so the revision round-trips; it can fail
if a downgraded DB holds cross-tenant duplicate keys, which is the inherent
reverse of removing a too-broad uniqueness rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_0003"
down_revision: str | Sequence[str] | None = "20260614_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint_name) for the slice-1 global idempotency_key uniques.
_FACT_IDEMPOTENCY_UNIQUES = (
    ("repayments", "uq_repayments_idempotency_key"),
    ("debt_adjustments", "uq_debt_adjustments_idempotency_key"),
    ("repayment_voids", "uq_repayment_voids_idempotency_key"),
    ("debt_voids", "uq_debt_voids_idempotency_key"),
)


def upgrade() -> None:
    for table, name in _FACT_IDEMPOTENCY_UNIQUES:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{name}"')


def downgrade() -> None:
    for table, name in _FACT_IDEMPOTENCY_UNIQUES:
        op.create_unique_constraint(name, table, ["idempotency_key"])
