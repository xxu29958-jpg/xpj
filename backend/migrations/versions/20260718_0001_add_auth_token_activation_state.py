"""Add the Desktop pending-token activation state.

Revision ID: 20260718_0001
Revises: 20260711_0001

Pending Desktop credentials must coexist with the currently active credential
until the Manager has durably stored the replacement.  The active-principal
unique index therefore excludes pending rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0001"
down_revision: str | Sequence[str] | None = "20260711_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "auth_tokens"
_COLUMN = "activation_state"
_CHECK = "ck_auth_tokens_activation_state_valid"
_ACTIVE_INDEX = "uq_auth_tokens_active_principal"


def _columns(bind: sa.engine.Connection) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(bind).get_columns(_TABLE)
    }


def _indexes(bind: sa.engine.Connection) -> set[str]:
    return {
        str(index["name"])
        for index in sa.inspect(bind).get_indexes(_TABLE)
    }


def _checks(bind: sa.engine.Connection) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in sa.inspect(bind).get_check_constraints(_TABLE)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if _COLUMN not in _columns(bind):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
        )
    if _CHECK not in _checks(bind):
        op.create_check_constraint(
            _CHECK,
            _TABLE,
            "activation_state IN ('active', 'pending')",
        )
    if _ACTIVE_INDEX in _indexes(bind):
        op.drop_index(_ACTIVE_INDEX, table_name=_TABLE)
    op.create_index(
        _ACTIVE_INDEX,
        _TABLE,
        ["account_id", "device_id", "ledger_id", "scope"],
        unique=True,
        postgresql_where=sa.text(
            "revoked_at IS NULL AND activation_state = 'active'"
        ),
    )
    if "ix_auth_tokens_activation_state" not in _indexes(bind):
        op.create_index(
            "ix_auth_tokens_activation_state",
            _TABLE,
            [_COLUMN],
        )


def downgrade() -> None:
    raise NotImplementedError("20260718_0001 is forward-only")
