"""add desktop pending credential scope + activation receipts.

Revision ID: 20260720_0001
Revises: 20260715_0001
Create Date: 2026-07-20

Desktop pairing is a two-phase ceremony: the server first stages a
short-lived ``desktop_pending`` credential that every ordinary auth surface
rejects (the scope simply is not in any ``allowed_scopes`` set), and the only
way forward is the activate endpoint with the stable attempt proof. The
``desktop_activation_attempts`` receipt makes the response-loss replay return
the same committed activation instead of minting a second credential, and
records the lineage from the superseded predecessor token.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0001"
down_revision: str | Sequence[str] | None = "20260715_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_SCOPES = "('app', 'admin', 'desktop_pending')"


def _check_constraints(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _widen_auth_token_scope_check(bind) -> None:
    constraint_name = "ck_auth_tokens_scope_valid"
    if constraint_name in _check_constraints(bind, "auth_tokens"):
        op.drop_constraint(constraint_name, "auth_tokens", type_="check")
    invalid_scope = bind.scalar(
        sa.text(
            "SELECT scope FROM auth_tokens "
            "WHERE scope NOT IN ('app', 'admin', 'desktop_pending') LIMIT 1"
        )
    )
    if invalid_scope is not None:
        raise RuntimeError(
            "auth_tokens contains an invalid scope; refusing to widen "
            "ck_auth_tokens_scope_valid"
        )
    op.create_check_constraint(
        constraint_name,
        "auth_tokens",
        f"scope IN {_VALID_SCOPES}",
    )


def _create_desktop_activation_attempts(bind) -> None:
    if _has_table(bind, "desktop_activation_attempts"):
        return
    op.create_table(
        "desktop_activation_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("previous_token_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("ledger_id", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ledger_id"], ["ledgers.ledger_id"]),
        sa.ForeignKeyConstraint(["previous_token_id"], ["auth_tokens.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["auth_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_desktop_activation_attempts_public_id"),
        sa.UniqueConstraint("token_id", name="uq_desktop_activation_attempts_token_id"),
    )
    op.create_index(
        op.f("ix_desktop_activation_attempts_public_id"),
        "desktop_activation_attempts",
        ["public_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_desktop_activation_attempts_account_id"),
        "desktop_activation_attempts",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_desktop_activation_attempts_device_id"),
        "desktop_activation_attempts",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_desktop_activation_attempts_ledger_id"),
        "desktop_activation_attempts",
        ["ledger_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_desktop_activation_attempts_expires_at"),
        "desktop_activation_attempts",
        ["expires_at"],
        unique=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    _widen_auth_token_scope_check(bind)
    _create_desktop_activation_attempts(bind)


def downgrade() -> None:
    # The receipt table is the authoritative record of which staged desktop
    # credentials were activated; dropping it would let a replayed pending
    # proof mint a second session. Forward-only, like the identity receipts.
    raise RuntimeError("irreversible desktop activation receipt")
