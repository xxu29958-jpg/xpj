"""ADR-0049 P2: Debt 母表 shape CHECK backstops.

Revision ID: 20260619_0001
Revises: 20260618_0001
Create Date: 2026-06-19

Adds two CHECK constraints that push the Debt mother-table shape invariants the
service already maintains (``_create._clean_counterparty`` + ``create_bill_split_debt``)
down to the DB (model-invariant hardening P2,
docs/audits/2026-06-19-model-invariant-hardening.md):

- ``ck_debts_member_has_account``: ``(counterparty_type='member') = (counterparty_account_id IS NOT NULL)``
  — a member counterparty is identified by an internal account; an external one never is.
- ``ck_debts_bill_split_has_source_id``: ``(source_type='bill_split') = (source_id IS NOT NULL)``
  — a bill_split Debt always names its source invitation; a manual Debt never carries a source_id.

(counterparty_label presence is intentionally NOT constrained: it is display provenance, not a
structural identity field — the account check above is the identity invariant.)

The ORM model (app/models/debt.py) is the single source: init_db's create_all builds both
on a FRESH DB, so this migration is a guarded no-op there and only does real work advancing an
EXISTING PostgreSQL DB by Alembic. Like every tightening migration the ADD VALIDATEs existing
rows — on a dirty DB (a member Debt with no account, or a bill_split Debt with no source_id)
the ALTER raises rather than corrupt; data-correctness first.
With DEBT_ROLLOUT off, all existing prod Debt is external+manual, which satisfies the external/
manual side of every biconditional, so this is a zero-row-rejection tightening on prod. downgrade
drops the two by name (re-loosening; cannot fail). Predicate text is kept byte-identical to the
CheckConstraint text in app/models/debt.py by manual convention (the round-trip test asserts match).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0001"
down_revision: str | Sequence[str] | None = "20260618_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEBTS = "debts"

# (check_name, predicate) — byte-identical to app/models/debt.py CheckConstraint text.
_CHECKS: list[tuple[str, str]] = [
    (
        "ck_debts_member_has_account",
        "(counterparty_type = 'member') = (counterparty_account_id IS NOT NULL)",
    ),
    (
        "ck_debts_bill_split_has_source_id",
        "(source_type = 'bill_split') = (source_id IS NOT NULL)",
    ),
]


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_check(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in sa.inspect(bind).get_check_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _DEBTS):
        return
    for name, predicate in _CHECKS:
        if not _has_check(bind, _DEBTS, name):
            op.create_check_constraint(name, _DEBTS, predicate)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _DEBTS):
        return
    for name, _predicate in _CHECKS:
        if _has_check(bind, _DEBTS, name):
            op.drop_constraint(name, _DEBTS, type_="check")
