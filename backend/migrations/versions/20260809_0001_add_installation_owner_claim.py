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
_STRING_COLUMNS = {
    "operation_id": 128,
    "installation_id": 128,
    "request_fingerprint": 64,
    "active_secret_hash": 64,
    "ledger_id": 64,
}
_INTEGER_COLUMNS = {
    "account_id",
    "device_id",
    "pairing_code_id",
    "pairing_derivation_index",
    "generation",
}
_DATETIME_COLUMNS = {"created_at", "updated_at"}
_CHECKS = {
    "ck_installation_owner_claim_generation",
    "ck_installation_owner_claim_pairing_index",
    "ck_installation_owner_claim_request_fingerprint",
    "ck_installation_owner_claim_secret_hash",
}
_UNIQUES = {
    "uq_installation_owner_claim_active_secret_hash": ("active_secret_hash",),
    "uq_installation_owner_claim_installation_id": ("installation_id",),
    "uq_installation_owner_claim_pairing_code_id": ("pairing_code_id",),
}
_FOREIGN_KEYS = {
    "fk_installation_owner_claim_account": (
        ("account_id",), "accounts", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_device": (
        ("device_id",), "devices", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_ledger": (
        ("ledger_id",), "ledgers", ("ledger_id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_pairing": (
        ("pairing_code_id",), "pairing_codes", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_secret": (
        ("active_secret_hash",),
        "bootstrap_secret_consumptions",
        ("secret_hash",),
        "RESTRICT",
    ),
}
_INDEXES = {
    "pk_installation_owner_claims",
    *_UNIQUES,
}


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


def assert_postcondition(bind: sa.Connection) -> None:
    """Prove the generic installation-owner receipt before migration commit."""

    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names(schema="public"):
        raise RuntimeError("installation-owner postcondition is missing its receipt table")

    columns = {
        str(column["name"]): column
        for column in inspector.get_columns(_TABLE, schema="public")
    }
    expected_columns = set(_STRING_COLUMNS) | _INTEGER_COLUMNS | _DATETIME_COLUMNS
    if set(columns) != expected_columns or any(
        bool(column["nullable"]) for column in columns.values()
    ):
        raise RuntimeError("installation-owner postcondition columns drifted")
    for name, length in _STRING_COLUMNS.items():
        column_type = columns[name]["type"]
        if not isinstance(column_type, sa.String) or column_type.length != length:
            raise RuntimeError("installation-owner postcondition string columns drifted")
    if any(
        not isinstance(columns[name]["type"], sa.Integer)
        for name in _INTEGER_COLUMNS
    ):
        raise RuntimeError("installation-owner postcondition integer columns drifted")
    if any(
        not isinstance(columns[name]["type"], sa.DateTime)
        or not bool(columns[name]["type"].timezone)
        for name in _DATETIME_COLUMNS
    ):
        raise RuntimeError("installation-owner postcondition timestamps drifted")

    primary_key = inspector.get_pk_constraint(_TABLE, schema="public")
    if (
        primary_key.get("name") != "pk_installation_owner_claims"
        or tuple(primary_key.get("constrained_columns") or ()) != ("operation_id",)
    ):
        raise RuntimeError("installation-owner postcondition primary key drifted")
    checks = {
        str(check["name"])
        for check in inspector.get_check_constraints(_TABLE, schema="public")
    }
    if checks != _CHECKS:
        raise RuntimeError("installation-owner postcondition checks drifted")
    uniques = {
        str(unique["name"]): tuple(unique["column_names"])
        for unique in inspector.get_unique_constraints(_TABLE, schema="public")
    }
    if uniques != _UNIQUES:
        raise RuntimeError("installation-owner postcondition unique constraints drifted")
    foreign_keys = {
        str(foreign_key["name"]): (
            tuple(foreign_key["constrained_columns"]),
            str(foreign_key["referred_table"]),
            tuple(foreign_key["referred_columns"]),
            str(foreign_key.get("options", {}).get("ondelete", "")),
        )
        for foreign_key in inspector.get_foreign_keys(_TABLE, schema="public")
    }
    if foreign_keys != _FOREIGN_KEYS:
        raise RuntimeError("installation-owner postcondition foreign keys drifted")

    indexes = {
        str(index_name)
        for (index_name,) in bind.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :table"
            ),
            {"table": _TABLE},
        )
    }
    if indexes != _INDEXES:
        raise RuntimeError("installation-owner postcondition indexes drifted")
    unvalidated = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM pg_constraint "
            "WHERE conrelid = to_regclass(:table) AND NOT convalidated"
        ),
        {"table": f"public.{_TABLE}"},
    )
    if int(unvalidated or 0) != 0:
        raise RuntimeError("installation-owner postcondition has unvalidated constraints")

    invalid_rows = bind.scalar(
        sa.text(
            f"""
            SELECT COUNT(*)
              FROM public.{_TABLE}
             WHERE operation_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}$'
                OR installation_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}$'
                OR updated_at < created_at
            """
        )
    )
    if int(invalid_rows or 0) != 0:
        raise RuntimeError("installation-owner postcondition found malformed receipts")


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
