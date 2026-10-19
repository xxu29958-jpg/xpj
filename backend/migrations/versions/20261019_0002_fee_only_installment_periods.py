"""Retain scheduled fees after their principal has been settled."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0002"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    changed = op.get_bind().execute(sa.text(
        "UPDATE dataset_authority SET schema_revision=:target WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"),
        {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the fee-only period migration edge")


def upgrade():
    op.drop_constraint("ck_installment_periods_principal_minor_money_bounds", "installment_periods", type_="check")
    op.create_check_constraint("ck_installment_periods_principal_minor_money_bounds", "installment_periods",
                               "principal_minor BETWEEN 0 AND 9000000000000")
    op.create_check_constraint("ck_installment_period_nonempty", "installment_periods", "principal_minor > 0 OR planned_fee_minor > 0")
    _set_revision(down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM installment_periods WHERE principal_minor=0)")):
        raise RuntimeError("Retained fee-only periods need a supported reader; downgrade refused.")
    op.drop_constraint("ck_installment_period_nonempty", "installment_periods", type_="check")
    op.drop_constraint("ck_installment_periods_principal_minor_money_bounds", "installment_periods", type_="check")
    op.create_check_constraint("ck_installment_periods_principal_minor_money_bounds", "installment_periods",
                               "principal_minor BETWEEN 1 AND 9000000000000")
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    constraints = {row["name"]: row["sqltext"] for row in sa.inspect(bind).get_check_constraints("installment_periods")}
    if "ck_installment_period_nonempty" not in constraints or ">= 0" not in constraints.get("ck_installment_periods_principal_minor_money_bounds", ""):
        raise RuntimeError("fee-only installment period guards are missing")
