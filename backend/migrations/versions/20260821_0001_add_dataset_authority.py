"""Create the sole dataset authority and retire legacy identity rows.

Revision ID: 20260821_0001
Revises: 20260809_0001
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260821_0001"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None

_TABLE = "dataset_authority"
_SEMANTIC_REVISION = "ticketbox-dataset-semantics-v1"
_SCHEMA_MIN_COMPATIBLE = "1.2.0"
_LEGACY_KEYS = (
    "server_id",
    "data_generation",
    "schema_version",
    "schema_min_compatible",
)
_COLUMNS = {
    "singleton_id",
    "dataset_id",
    "restore_epoch",
    "schema_revision",
    "schema_min_compatible",
    "semantic_revision",
    "created_at",
    "restored_from_backup_id",
}
_CHECKS = {
    "ck_dataset_authority_singleton",
    "ck_dataset_authority_restore_epoch",
    "ck_dataset_authority_dataset_id",
    "ck_dataset_authority_schema_revision",
    "ck_dataset_authority_semantic_revision",
    "ck_dataset_authority_backup_id",
}


def _canonical_uuid(value: object, *, label: str) -> str:
    try:
        canonical = str(UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"legacy {label} is not a UUID") from exc
    if value != canonical:
        raise RuntimeError(f"legacy {label} is not canonical")
    return canonical


def _create_table(bind: sa.Connection) -> None:
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("singleton_id", sa.SmallInteger(), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("restore_epoch", sa.BigInteger(), nullable=False),
        sa.Column("schema_revision", sa.String(length=32), nullable=False),
        sa.Column("schema_min_compatible", sa.String(length=64), nullable=False),
        sa.Column("semantic_revision", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_from_backup_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "singleton_id = 1",
            name="ck_dataset_authority_singleton",
        ),
        sa.CheckConstraint(
            "restore_epoch >= 0",
            name="ck_dataset_authority_restore_epoch",
        ),
        sa.CheckConstraint(
            "dataset_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_dataset_authority_dataset_id",
        ),
        sa.CheckConstraint(
            "schema_revision ~ '^[0-9]{8}_[0-9]{4}$'",
            name="ck_dataset_authority_schema_revision",
        ),
        sa.CheckConstraint(
            "semantic_revision ~ '^ticketbox-dataset-semantics-v[1-9][0-9]*$'",
            name="ck_dataset_authority_semantic_revision",
        ),
        sa.CheckConstraint(
            "restored_from_backup_id IS NULL OR restored_from_backup_id ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_dataset_authority_backup_id",
        ),
        sa.PrimaryKeyConstraint("singleton_id", name="pk_dataset_authority"),
    )


def _seed_and_retire_legacy_rows(bind: sa.Connection) -> None:
    existing = bind.execute(sa.text(f'SELECT dataset_id FROM "{_TABLE}" WHERE singleton_id = 1')).scalar_one_or_none()
    if existing is None:
        bind.execute(
            sa.text(
                f'INSERT INTO "{_TABLE}" '
                "(singleton_id, dataset_id, restore_epoch, schema_revision, "
                "schema_min_compatible, semantic_revision, created_at, "
                "restored_from_backup_id) VALUES "
                "(1, :dataset_id, 0, :schema_revision, :minimum, :semantic_revision, "
                ":created_at, NULL)"
            ),
            {
                "dataset_id": str(uuid4()),
                "schema_revision": revision,
                "minimum": _SCHEMA_MIN_COMPATIBLE,
                "semantic_revision": _SEMANTIC_REVISION,
                "created_at": datetime.now(UTC),
            },
        )
    bind.execute(
        sa.text("DELETE FROM app_meta WHERE key = ANY(:keys)"),
        {"keys": list(_LEGACY_KEYS)},
    )


def upgrade() -> None:
    bind = op.get_bind()
    _create_table(bind)
    _seed_and_retire_legacy_rows(bind)
    assert_postcondition(bind)


def downgrade() -> None:
    raise RuntimeError("dataset authority downgrade is not supported")


def assert_postcondition(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        raise RuntimeError("dataset_authority table is missing")
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    checks = {check["name"] for check in inspector.get_check_constraints(_TABLE)}
    primary_key = inspector.get_pk_constraint(_TABLE).get("constrained_columns")
    if columns != _COLUMNS or checks != _CHECKS or primary_key != ["singleton_id"]:
        raise RuntimeError("dataset_authority schema is incomplete")
    rows = (
        bind.execute(
            sa.text(
                f"SELECT dataset_id, restore_epoch, schema_revision, "
                f"schema_min_compatible, semantic_revision, restored_from_backup_id "
                f'FROM "{_TABLE}"'
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise RuntimeError("dataset authority must contain exactly one row")
    row = rows[0]
    _canonical_uuid(row["dataset_id"], label="dataset_id")
    if (
        row["restore_epoch"] != 0
        or row["schema_revision"] != revision
        or not row["schema_min_compatible"]
        or row["semantic_revision"] != _SEMANTIC_REVISION
        or row["restored_from_backup_id"] is not None
    ):
        raise RuntimeError("dataset authority seed is invalid")
    legacy_count = bind.scalar(
        sa.text("SELECT COUNT(*) FROM app_meta WHERE key = ANY(:keys)"),
        {"keys": list(_LEGACY_KEYS)},
    )
    if legacy_count:
        raise RuntimeError("legacy dataset identity rows remain writable")
