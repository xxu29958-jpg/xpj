"""Retain a private original before debt-bill suggestions and explicit adoption."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261028_0001"
down_revision = "20261023_0002"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the debt-bill capture migration edge")


def upgrade():
    op.create_table("debt_bill_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("ledgers.ledger_id"), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("creation_key", sa.String(64), nullable=False),
        sa.Column("capture_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("accepted_receipt", JSONB(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=False),
        sa.Column("image_hash", sa.String(64), nullable=False),
        sa.Column("image_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("image_evidence", JSONB()),
        sa.Column("image_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("attachment_cleanup_request", JSONB()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("parse_attempt_key", sa.String(64)),
        sa.Column("parse_request_fingerprint", sa.String(64)),
        sa.Column("parse_outcome", JSONB()),
        sa.Column("adopted_debt_public_id", sa.String(36), sa.ForeignKey("debts.public_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "capture_key", name="uq_debt_bill_capture_key"),
        sa.UniqueConstraint("adopted_debt_public_id", name="uq_debt_bill_capture_debt"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="ck_debt_bill_capture_status"),
        sa.CheckConstraint("row_version > 0 AND image_size_bytes > 0", name="ck_debt_bill_capture_version_size"))
    _set_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM debt_bill_captures)")):
        raise RuntimeError("cannot erase retained debt-bill originals or their accepted tasks")
    op.drop_table("debt_bill_captures")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {item["name"]: item for item in inspector.get_columns("debt_bill_captures")}
    required = {"accepted_receipt", "image_path", "image_hash", "input_sha256", "creation_key", "capture_key"}
    if not required <= columns.keys() or any(columns[name]["nullable"] for name in required):
        raise RuntimeError("debt-bill original identity or acceptance evidence is missing")
    unique = {item["name"] for item in inspector.get_unique_constraints("debt_bill_captures")}
    if not {"uq_debt_bill_capture_key", "uq_debt_bill_capture_debt"} <= unique:
        raise RuntimeError("debt-bill capture identity constraints are missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != (revision if live == down_revision else live):
        raise RuntimeError("dataset authority is not aligned with debt-bill capture evidence")
