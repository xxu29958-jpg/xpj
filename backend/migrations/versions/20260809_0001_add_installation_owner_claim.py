"""Add the recoverable Windows installation-owner claim.

Revision ID: 20260809_0001
Revises: 20260802_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260809_0001"
down_revision = "20260802_0001"
branch_labels = None
depends_on = None

_TABLE = "installation_owner_claims"


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("installation_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("ledger_id", sa.String(length=64), nullable=False),
        sa.Column("pairing_code_id", sa.Integer(), nullable=False),
        sa.Column("pairing_derivation_index", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_installation_owner_claim_request_fingerprint",
        ),
        sa.CheckConstraint(
            "active_secret_hash ~ '^[0-9a-f]{64}$'",
            name="ck_installation_owner_claim_secret_hash",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_installation_owner_claim_generation",
        ),
        sa.CheckConstraint(
            "pairing_derivation_index BETWEEN 0 AND 63",
            name="ck_installation_owner_claim_pairing_index",
        ),
        sa.ForeignKeyConstraint(
            ["active_secret_hash"],
            ["bootstrap_secret_consumptions.secret_hash"],
            name="fk_installation_owner_claim_secret",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_installation_owner_claim_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_installation_owner_claim_device",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_id"],
            ["ledgers.ledger_id"],
            name="fk_installation_owner_claim_ledger",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pairing_code_id"],
            ["pairing_codes.id"],
            name="fk_installation_owner_claim_pairing",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "operation_id",
            name="pk_installation_owner_claims",
        ),
        sa.UniqueConstraint(
            "installation_id",
            name="uq_installation_owner_claim_installation_id",
        ),
        sa.UniqueConstraint(
            "active_secret_hash",
            name="uq_installation_owner_claim_active_secret_hash",
        ),
        sa.UniqueConstraint(
            "pairing_code_id",
            name="uq_installation_owner_claim_pairing_code_id",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        claim_count = bind.execute(
            sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')
        ).scalar_one()
        if claim_count:
            raise RuntimeError(
                "installation_owner_claims contains persistent installation "
                "identity; destructive downgrade is refused"
            )
        op.drop_table(_TABLE)
