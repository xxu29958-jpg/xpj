"""add recoverable device enrollment attempts.

Revision ID: 20260715_0001
Revises: 20260711_0001
Create Date: 2026-07-15

Pairing codes and invitations both create or recover a Device session. If the
HTTP response is lost after commit, a client-proved attempt lets a retry reuse
the first Account, Device, and session. Pairing codes can also explicitly
target an existing Device for user-approved recovery of its local outbox.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "20260715_0001"
down_revision: str | Sequence[str] | None = "20260711_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_pairing_recovery_target() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("pairing_codes")}
    if "recovery_device_id" in columns:
        return
    op.add_column(
        "pairing_codes",
        sa.Column("recovery_device_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pairing_codes_recovery_device_id_devices",
        "pairing_codes",
        "devices",
        ["recovery_device_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_pairing_codes_recovery_device_id"),
        "pairing_codes",
        ["recovery_device_id"],
        unique=False,
    )


def _create_device_enrollment_attempts() -> None:
    op.create_table(
        "device_enrollment_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("pairing_code_id", sa.Integer(), nullable=True),
        sa.Column("invitation_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("ledger_id", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "session_soft_refresh_after",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["ledger_id"], ["ledgers.ledger_id"]),
        sa.ForeignKeyConstraint(
            ["pairing_code_id"],
            ["pairing_codes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["invitations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(pairing_code_id IS NOT NULL) <> (invitation_id IS NOT NULL)",
            name="ck_device_enrollment_attempts_one_source",
        ),
        sa.UniqueConstraint(
            "pairing_code_id",
            name="uq_device_enrollment_attempts_pairing_code_id",
        ),
        sa.UniqueConstraint(
            "invitation_id",
            name="uq_device_enrollment_attempts_invitation_id",
        ),
    )
    op.create_index(
        op.f("ix_device_enrollment_attempts_account_id"),
        "device_enrollment_attempts",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_enrollment_attempts_device_id"),
        "device_enrollment_attempts",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_enrollment_attempts_expires_at"),
        "device_enrollment_attempts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_enrollment_attempts_ledger_id"),
        "device_enrollment_attempts",
        ["ledger_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_enrollment_attempts_public_id"),
        "device_enrollment_attempts",
        ["public_id"],
        unique=True,
    )


def _create_session_refresh_attempts() -> None:
    op.create_table(
        "session_refresh_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("source_token_id", sa.Integer(), nullable=False),
        sa.Column("replacement_token_id", sa.Integer(), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "session_soft_refresh_after",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_token_id"],
            ["auth_tokens.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_token_id"],
            ["auth_tokens.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_token_id",
            name="uq_session_refresh_attempts_source_token_id",
        ),
        sa.UniqueConstraint(
            "replacement_token_id",
            name="uq_session_refresh_attempts_replacement_token_id",
        ),
    )
    op.create_index(
        op.f("ix_session_refresh_attempts_expires_at"),
        "session_refresh_attempts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_session_refresh_attempts_public_id"),
        "session_refresh_attempts",
        ["public_id"],
        unique=True,
    )


def _replace_rule_batch_device_fk(*, ondelete: str | None) -> None:
    inspector = sa.inspect(op.get_bind())
    foreign_key = next(
        (
            candidate
            for candidate in inspector.get_foreign_keys("rule_application_batches")
            if candidate["constrained_columns"] == ["actor_device_id"] and candidate["referred_table"] == "devices"
        ),
        None,
    )
    if foreign_key is None or not foreign_key["name"]:
        raise RuntimeError("rule application device foreign key is missing")
    if foreign_key.get("options", {}).get("ondelete") == ondelete:
        return
    op.drop_constraint(
        foreign_key["name"],
        "rule_application_batches",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_rule_application_batches_actor_device_id_devices",
        "rule_application_batches",
        "devices",
        ["actor_device_id"],
        ["id"],
        ondelete=ondelete,
    )


def _provision_server_data_identity() -> None:
    app_meta = sa.table(
        "app_meta",
        sa.column("key", sa.String(length=64)),
        sa.column("value", sa.Text()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    created_at = datetime.now(UTC)
    op.get_bind().execute(
        insert(app_meta)
        .values(
            [
                {"key": "server_id", "value": str(uuid4()), "updated_at": created_at},
                {"key": "data_generation", "value": str(uuid4()), "updated_at": created_at},
            ]
        )
        .on_conflict_do_nothing(index_elements=[app_meta.c.key])
    )


def upgrade() -> None:
    _add_pairing_recovery_target()
    _replace_rule_batch_device_fk(ondelete="SET NULL")
    if not sa.inspect(op.get_bind()).has_table("device_enrollment_attempts"):
        _create_device_enrollment_attempts()
    if not sa.inspect(op.get_bind()).has_table("session_refresh_attempts"):
        _create_session_refresh_attempts()
    _provision_server_data_identity()


def downgrade() -> None:
    # These tables are the only replay evidence for already-committed device
    # enrollment and token rotation. Dropping them while leaving the issued
    # Device/AuthToken rows would turn an ordinary response loss into an
    # unrecoverable identity fork. Binary rollback remains supported at this
    # schema; destructive schema downgrade does not.
    raise RuntimeError(
        "20260715_0001 is an irreversible identity receipt migration; "
        "roll back the binary without downgrading the database"
    )
