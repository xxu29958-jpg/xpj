"""bind repayment_drafts idempotency to the account scope.

Revision ID: 20260722_0001
Revises: 20260720_0001
Create Date: 2026-07-22

Issue #224 (C3) / ADR-0049 §8 privacy: ``uq_repayment_drafts_idem`` was only
``(tenant_id, draft_idempotency_key)`` while a repayment capture is PERSONAL (one
member's phone payment notification). Two members of one ledger capturing the same
notification content collided on the tenant-wide constraint — worse, the service's
account-less first-check returned the OTHER member's draft (cross-account leak).

The ORM now declares the constraint over ``(tenant_id, created_by_account_id,
draft_idempotency_key)`` and the create path's first-check / IntegrityError race
re-check both filter ``created_by_account_id``. This forward revision swaps the
constraint on any DB that applied 20260617_0001, rather than editing that merged
revision in place (which would leave already-migrated databases with the stale
tenant-wide constraint).

No backfill: ``created_by_account_id`` is already NOT NULL on every row, and the new
constraint is strictly WEAKER (a superset key) than the old one, so existing data
cannot violate it. ``DROP CONSTRAINT IF EXISTS`` keeps the revision a no-op-safe
replacement on every path: the normal ``init_db`` path is ``create_all`` (from the
current models, which declare the account-scoped constraint) + ``alembic stamp`` +
``upgrade head``; on that path this body never runs, and on a pure-Alembic DB the old
constraint is dropped and re-created in the account-scoped form.

``downgrade`` re-adds the tenant-wide constraint so the revision round-trips; it can
fail if a downgraded DB holds cross-account duplicate keys, which is the inherent
reverse of narrowing a uniqueness rule.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260722_0001"
down_revision: str | Sequence[str] | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "repayment_drafts"
_CONSTRAINT = "uq_repayment_drafts_idem"
_ACCOUNT_SCOPED_COLUMNS = ["tenant_id", "created_by_account_id", "draft_idempotency_key"]
_TENANT_SCOPED_COLUMNS = ["tenant_id", "draft_idempotency_key"]


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table(_TABLE):
        return
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_CONSTRAINT}"')
    op.create_unique_constraint(_CONSTRAINT, _TABLE, _ACCOUNT_SCOPED_COLUMNS)


def downgrade() -> None:
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_CONSTRAINT}"')
    op.create_unique_constraint(_CONSTRAINT, _TABLE, _TENANT_SCOPED_COLUMNS)
