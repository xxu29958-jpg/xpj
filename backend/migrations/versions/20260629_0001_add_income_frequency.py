"""add income frequency and one-time income month.

Revision ID: 20260629_0001
Revises: 20260624_0001
Create Date: 2026-06-29

Existing income rows remain monthly recurring income. New one-time rows carry
``frequency='one_time'`` plus a ``YYYY-MM`` ``income_month`` so monthly budget
math can include them only in the month where they apply.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260629_0001"
down_revision: str | Sequence[str] | None = "20260624_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "monthly_income_plans"
_FREQUENCY_CHECK = "ck_monthly_income_plans_frequency_valid"
_INCOME_MONTH_SHAPE_CHECK = "ck_monthly_income_plans_income_month_shape"
_FREQUENCY_PREDICATE = "frequency IN ('monthly', 'one_time')"
_INCOME_MONTH_SHAPE_PREDICATE = (
    "(frequency = 'monthly' AND income_month IS NULL) OR "
    "(frequency = 'one_time' AND income_month IS NOT NULL)"
)
_INDEX = "ix_monthly_income_plans_tenant_status_frequency_month"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def _has_check(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in sa.inspect(bind).get_check_constraints(table))


def _has_index(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(i.get("name") == name for i in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if not _has_column(bind, _TABLE, "frequency"):
        op.add_column(
            _TABLE,
            sa.Column(
                "frequency",
                sa.String(length=16),
                nullable=False,
                server_default="monthly",
            ),
        )
    if not _has_column(bind, _TABLE, "income_month"):
        op.add_column(_TABLE, sa.Column("income_month", sa.String(length=7), nullable=True))
    if not _has_check(bind, _TABLE, _FREQUENCY_CHECK):
        op.create_check_constraint(_FREQUENCY_CHECK, _TABLE, _FREQUENCY_PREDICATE)
    if not _has_check(bind, _TABLE, _INCOME_MONTH_SHAPE_CHECK):
        op.create_check_constraint(
            _INCOME_MONTH_SHAPE_CHECK,
            _TABLE,
            _INCOME_MONTH_SHAPE_PREDICATE,
        )
    if not _has_index(bind, _TABLE, _INDEX):
        op.create_index(
            _INDEX,
            _TABLE,
            ["tenant_id", "status", "frequency", "income_month"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if _has_index(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_check(bind, _TABLE, _INCOME_MONTH_SHAPE_CHECK):
        op.drop_constraint(_INCOME_MONTH_SHAPE_CHECK, _TABLE, type_="check")
    if _has_check(bind, _TABLE, _FREQUENCY_CHECK):
        op.drop_constraint(_FREQUENCY_CHECK, _TABLE, type_="check")
    if _has_column(bind, _TABLE, "income_month"):
        op.drop_column(_TABLE, "income_month")
    if _has_column(bind, _TABLE, "frequency"):
        op.drop_column(_TABLE, "frequency")
