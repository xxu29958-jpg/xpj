"""Keep incurred fees linked to their one Expense and optional schedule."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0003"
down_revision = "20261019_0002"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    result = op.get_bind().execute(sa.text(
        "UPDATE dataset_authority SET schema_revision=:target WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"),
        {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the credit fee migration edge")


def upgrade():
    op.create_table("credit_fee_obligations",
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("expenses.id"), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("installment_periods.id")))
    op.create_index("ix_credit_fee_obligations_account_id", "credit_fee_obligations", ["account_id"])
    _set_revision(down_revision, revision)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM credit_fee_obligations)")):
        raise RuntimeError("Incurred fee identities and settlements must remain readable; downgrade refused.")
    op.drop_table("credit_fee_obligations")
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    if not inspector.has_table("credit_fee_obligations") or {
            tuple(row["constrained_columns"]) for row in inspector.get_foreign_keys("credit_fee_obligations")
    } != {("expense_id",), ("account_id",), ("period_id",)}:
        raise RuntimeError("incurred fee source relations are missing")
