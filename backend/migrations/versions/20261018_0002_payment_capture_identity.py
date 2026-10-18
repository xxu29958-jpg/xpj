"""Retain a notification identity across candidate classification and correction."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261018_0002"
down_revision = "20261018_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the payment capture migration edge")


def upgrade():
    op.create_table("payment_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("ledgers.ledger_id"), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("identity_hash", sa.String(64)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_currency", sa.String(3), nullable=False),
        sa.Column("original_amount_minor", sa.BigInteger()),
        sa.Column("merchant", sa.String(255)),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("candidates", JSONB(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("expense_public_id", sa.String(36)),
        sa.Column("repayment_public_id", sa.String(36)),
        sa.Column("decisions", JSONB(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_account_id", "identity_hash", name="uq_payment_capture_identity"),
        sa.UniqueConstraint("repayment_public_id", name="uq_payment_capture_repayment"),
        sa.UniqueConstraint("expense_public_id", name="uq_payment_capture_expense"),
        sa.CheckConstraint("kind IN ('review', 'expense', 'repayment', 'dismissed')", name="ck_payment_capture_kind"),
        sa.CheckConstraint("row_version > 0", name="ck_payment_capture_version"),
        sa.CheckConstraint("original_amount_minor IS NULL OR original_amount_minor > 0", name="ck_payment_capture_amount"))
    _set_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM payment_captures)")):
        raise RuntimeError("cannot erase original notification identities or correction history")
    op.drop_table("payment_captures")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    required = {"uq_payment_capture_identity", "uq_payment_capture_repayment", "uq_payment_capture_expense"}
    if not required <= {item["name"] for item in inspector.get_unique_constraints("payment_captures")}:
        raise RuntimeError("payment capture identity constraints are missing")
