"""ADR-0049 #4: member-repayment lifecycle DB constraint backstops.

Revision ID: 20260618_0001
Revises: 20260617_0001
Create Date: 2026-06-18

Adds the FK + status-consistency CHECK backstops that let the DB enforce member-repayment
invariants the service already maintains (functional-correctness hardening #4):

- FK ``repayments.proposal_id`` -> ``member_repayment_proposals.id`` (RESTRICT)
- FK ``member_repayment_proposals.committed_repayment_id`` -> ``repayments.id`` (RESTRICT)
  — the nullable circular back-link; in the ORM its ForeignKey is ``use_alter=True`` so
  create_all on a fresh DB breaks the table-ordering cycle, but a plain ADD CONSTRAINT
  here is order-independent because both tables already exist on the migrate path.
- self-ref FK ``member_repayment_proposals.supersedes_proposal_id`` -> ``...(id)`` (RESTRICT)
- CHECK ``ck_mrp_committed_iff_confirmed``: committed_repayment_id NOT NULL iff status is
  confirmed / partially_confirmed.
- CHECK ``ck_mrp_confirmed_amount_iff_confirmed``: same biconditional for confirmed_amount_cents.
- CHECK ``ck_repayment_drafts_committed_iff_confirmed``: a RepaymentDraft's
  committed_repayment_public_id is set iff the draft was confirmed (same lifecycle class).

The ORM models (app/models/debt.py) are the single source: init_db's create_all builds
all six on a FRESH DB, so this migration is a guarded no-op there and only does real work
advancing an EXISTING PostgreSQL DB by Alembic. Like every tightening migration the upgrade
ADDs VALIDATE existing rows — on a dirty DB (a (partially_)confirmed proposal with a NULL
committed_repayment_id / confirmed_amount_cents, or a back-link int that doesn't resolve to a
live row) the ALTER raises rather than corrupt; data-correctness first. downgrade drops all
six by name (re-loosening; cannot fail).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0001"
down_revision: str | Sequence[str] | None = "20260617_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MRP = "member_repayment_proposals"
_DRAFTS = "repayment_drafts"

# (table, fk_name, referent_table, local_cols, remote_cols)
_FOREIGN_KEYS: list[tuple[str, str, str, list[str], list[str]]] = [
    ("repayments", "fk_repayments_proposal", _MRP, ["proposal_id"], ["id"]),
    (_MRP, "fk_mrp_committed_repayment", "repayments", ["committed_repayment_id"], ["id"]),
    (_MRP, "fk_mrp_supersedes_proposal", _MRP, ["supersedes_proposal_id"], ["id"]),
]

# (table, check_name, predicate) — kept byte-identical to the CheckConstraint text in
# app/models/debt.py by manual convention (no machine diff enforces this).
_CHECKS: list[tuple[str, str, str]] = [
    (
        _MRP,
        "ck_mrp_committed_iff_confirmed",
        "(status IN ('confirmed', 'partially_confirmed')) = (committed_repayment_id IS NOT NULL)",
    ),
    (
        _MRP,
        "ck_mrp_confirmed_amount_iff_confirmed",
        "(status IN ('confirmed', 'partially_confirmed')) = (confirmed_amount_cents IS NOT NULL)",
    ),
    (
        _DRAFTS,
        "ck_repayment_drafts_committed_iff_confirmed",
        "(status = 'confirmed') = (committed_repayment_public_id IS NOT NULL)",
    ),
]


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_fk(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in sa.inspect(bind).get_foreign_keys(table))


def _has_check(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in sa.inspect(bind).get_check_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _MRP) or not _has_table(bind, "repayments"):
        return
    for table, name, referent, local, remote in _FOREIGN_KEYS:
        if not _has_fk(bind, table, name):
            op.create_foreign_key(name, table, referent, local, remote, ondelete="RESTRICT")
    for table, name, predicate in _CHECKS:
        if _has_table(bind, table) and not _has_check(bind, table, name):
            op.create_check_constraint(name, table, predicate)


def downgrade() -> None:
    bind = op.get_bind()
    for table, name, _predicate in _CHECKS:
        if _has_table(bind, table) and _has_check(bind, table, name):
            op.drop_constraint(name, table, type_="check")
    for table, name, *_rest in _FOREIGN_KEYS:
        if _has_table(bind, table) and _has_fk(bind, table, name):
            op.drop_constraint(name, table, type_="foreignkey")
