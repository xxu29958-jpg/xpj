"""widen goals for debt_repayment + add debt_goal_links (ADR-0049 slice 6).

Revision ID: 20260615_0001
Revises: 20260614_0003
Create Date: 2026-06-15

ADR-0049 §6: the ``goals`` table grows from spending_limit-only to also carry
``debt_repayment`` goals (they link explicit Debt ids and latch achievement per
goal version instead of tracking a monthly spend target), plus the new
``debt_goal_links`` membership table (one row per (goal_version, Debt)).

Dual-write shape, same as 20260614_0001/0002/0003: ``init_db()`` runs
``Base.metadata.create_all`` from the CURRENT (final-shape) models AND THEN
``alembic upgrade head`` replays every revision from the stamped baseline
forward. So on a brand-new DB the ``goals`` table already has the final CHECKs /
nullable columns / new columns / scoped indexes and ``debt_goal_links`` already
exists — every step here must be an idempotent no-op. On an existing Postgres DB
(stamped at 20260614_0003) these ALTERs actually mutate the legacy shape.

Postgres CHECK constraints cannot be altered in place, so the three goals CHECKs
are DROP-then-ADD (``IF EXISTS`` so the fresh path, where ``create_all`` already
made the final-shape constraint, drops+re-adds an identical one and the legacy
path drops the old predicate first). The two partial-unique scope indexes are
DROP-then-CREATE with the new ``goal_type = 'spending_limit'`` predicate. The
three new columns are guarded by ``_has_column``; ``ALTER COLUMN ... DROP NOT
NULL`` is naturally idempotent. ``debt_goal_links`` create is guarded by a
table-name check (``create_all`` already made it on the fresh path / on an
existing DB ``create_all`` creates the new table before this revision runs).

``downgrade`` restores the spending_limit-only CHECKs / unscoped indexes and
drops the new columns + table; the ADD of the strict ``goal_type IN
('spending_limit')`` CHECK can fail if a downgraded DB already holds
``debt_repayment`` goals, which is the inherent reverse of widening a type
domain.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260615_0001"
down_revision: str | Sequence[str] | None = "20260614_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TOTAL_SCOPE_INDEX = "uq_goals_active_total_scope"
_CATEGORY_SCOPE_INDEX = "uq_goals_active_category_scope"

# Final-shape (slice 6) partial predicates, kept equivalent to the ORM
# ``postgresql_where`` in app/models/budget.py by manual convention.
_TOTAL_SCOPE_WHERE = "status = 'active' AND category IS NULL AND goal_type = 'spending_limit'"
_CATEGORY_SCOPE_WHERE = "status = 'active' AND category IS NOT NULL AND goal_type = 'spending_limit'"
# Legacy (pre-slice-6) predicates, used by ``downgrade``.
_LEGACY_TOTAL_SCOPE_WHERE = "status = 'active' AND category IS NULL"
_LEGACY_CATEGORY_SCOPE_WHERE = "status = 'active' AND category IS NOT NULL"


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _swap_goals_checks(*, allow_debt_repayment: bool) -> None:
    """DROP+ADD the three goals CHECKs (Postgres can't alter a CHECK in place).

    ``allow_debt_repayment`` picks the slice-6 (widened) predicates vs the legacy
    spending_limit-only ones, so this serves both upgrade and downgrade.
    """
    if allow_debt_repayment:
        type_pred = "goal_type IN ('spending_limit', 'debt_repayment')"
        month_pred = "goal_type <> 'spending_limit' OR length(month) = 7"
        target_pred = "goal_type <> 'spending_limit' OR target_amount_cents > 0"
    else:
        type_pred = "goal_type IN ('spending_limit')"
        month_pred = "length(month) = 7"
        target_pred = "target_amount_cents > 0"
    for name, predicate in (
        ("ck_goals_type_valid", type_pred),
        ("ck_goals_month_format", month_pred),
        ("ck_goals_target_positive", target_pred),
    ):
        op.execute(f'ALTER TABLE goals DROP CONSTRAINT IF EXISTS "{name}"')
        op.execute(f'ALTER TABLE goals ADD CONSTRAINT "{name}" CHECK ({predicate})')


def _recreate_scope_indexes(*, total_where: str, category_where: str) -> None:
    op.execute(f'DROP INDEX IF EXISTS "{_TOTAL_SCOPE_INDEX}"')
    op.execute(f'DROP INDEX IF EXISTS "{_CATEGORY_SCOPE_INDEX}"')
    op.create_index(
        _TOTAL_SCOPE_INDEX,
        "goals",
        ["tenant_id", "month", "goal_type", "period"],
        unique=True,
        postgresql_where=sa.text(total_where),
    )
    op.create_index(
        _CATEGORY_SCOPE_INDEX,
        "goals",
        ["tenant_id", "month", "goal_type", "period", "category"],
        unique=True,
        postgresql_where=sa.text(category_where),
    )


def _create_debt_goal_links() -> None:
    op.create_table(
        "debt_goal_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("goal_version", sa.Integer(), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], name="fk_debt_goal_links_goal"),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"], name="fk_debt_goal_links_debt"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goal_id", "goal_version", "debt_id", name="uq_debt_goal_links_goal_version_debt"
        ),
    )
    with op.batch_alter_table("debt_goal_links", schema=None) as batch_op:
        # ORM ``index=True`` auto-named indexes (``ix_<table>_<column>``) so the
        # create_all (legacy bridge) path and this Alembic path agree on names.
        batch_op.create_index("ix_debt_goal_links_goal_id", ["goal_id"], unique=False)
        batch_op.create_index("ix_debt_goal_links_debt_id", ["debt_id"], unique=False)
        # Explicit matching name in both the ORM ``Index(...)`` and here.
        batch_op.create_index(
            "ix_debt_goal_links_goal_version", ["goal_id", "goal_version"], unique=False
        )


def upgrade() -> None:
    bind = op.get_bind()

    # goals: nullable month / target (a debt_repayment goal has neither).
    # ``ALTER COLUMN ... DROP NOT NULL`` is idempotent — a no-op when create_all
    # already made the column nullable on the fresh path.
    with op.batch_alter_table("goals") as batch_op:
        batch_op.alter_column("month", existing_type=sa.String(length=7), nullable=True)
        batch_op.alter_column("target_amount_cents", existing_type=sa.Integer(), nullable=True)

    _swap_goals_checks(allow_debt_repayment=True)

    # goals: new debt_repayment columns (guarded — present already on the fresh
    # create_all path). goal_version backfills existing spending rows to 1 via
    # server_default, like 20260603_0001's row_version.
    if not _has_column(bind, "goals", "goal_version"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.add_column(
                sa.Column("goal_version", sa.Integer(), nullable=False, server_default="1")
            )
    if not _has_column(bind, "goals", "achieved_at"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.add_column(sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(bind, "goals", "achieved_version"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.add_column(sa.Column("achieved_version", sa.Integer(), nullable=True))

    # goals: scope indexes gain the goal_type='spending_limit' predicate.
    _recreate_scope_indexes(
        total_where=_TOTAL_SCOPE_WHERE, category_where=_CATEGORY_SCOPE_WHERE
    )

    # debt_goal_links: new membership table (guarded — create_all makes it first).
    if "debt_goal_links" not in set(sa.inspect(bind).get_table_names()):
        _create_debt_goal_links()


def downgrade() -> None:
    bind = op.get_bind()

    if "debt_goal_links" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("debt_goal_links")

    # Restore the legacy unscoped scope indexes.
    _recreate_scope_indexes(
        total_where=_LEGACY_TOTAL_SCOPE_WHERE, category_where=_LEGACY_CATEGORY_SCOPE_WHERE
    )

    if _has_column(bind, "goals", "achieved_version"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.drop_column("achieved_version")
    if _has_column(bind, "goals", "achieved_at"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.drop_column("achieved_at")
    if _has_column(bind, "goals", "goal_version"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.drop_column("goal_version")

    # Restore the spending_limit-only CHECKs. Fails if debt_repayment rows exist.
    _swap_goals_checks(allow_debt_repayment=False)
    with op.batch_alter_table("goals") as batch_op:
        batch_op.alter_column(
            "target_amount_cents", existing_type=sa.Integer(), nullable=False
        )
        batch_op.alter_column("month", existing_type=sa.String(length=7), nullable=False)
