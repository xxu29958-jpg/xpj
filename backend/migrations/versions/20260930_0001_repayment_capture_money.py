"""Keep captured original money without inventing a converted home amount.

Old rows keep their existing captured home money; their unknown original is not
reconstructed from today's rates or assumed to be CNY. No financial rows are rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0001"
down_revision = "20260927_0002"
branch_labels = None
depends_on = None

_SHAPE = (
    "(original_currency_code IS NULL AND original_amount_minor IS NULL AND amount_cents IS NOT NULL) "
    "OR (original_currency_code IS NOT NULL AND length(original_currency_code) = 3 "
    "AND original_amount_minor IS NOT NULL)"
)


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the repayment capture money edge")


def upgrade():
    op.add_column("repayment_drafts", sa.Column("original_currency_code", sa.String(3), nullable=True))
    op.add_column("repayment_drafts", sa.Column("original_amount_minor", sa.BigInteger(), nullable=True))
    op.alter_column("repayment_drafts", "amount_cents", existing_type=sa.BigInteger(), nullable=True)
    op.drop_constraint("ck_repayment_drafts_amount_cents_money_bounds", "repayment_drafts", type_="check")
    for column in ("amount_cents", "original_amount_minor"):
        op.create_check_constraint(f"ck_repayment_drafts_{column}_money_bounds", "repayment_drafts",
            f"{column} IS NULL OR ({column} BETWEEN 1 AND 9000000000000)")
    op.create_check_constraint("ck_repayment_drafts_captured_money", "repayment_drafts", _SHAPE)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM repayment_drafts "
        "WHERE original_currency_code IS NOT NULL OR amount_cents IS NULL)")):
        raise RuntimeError("cannot erase captured original repayment money")
    op.drop_constraint("ck_repayment_drafts_captured_money", "repayment_drafts", type_="check")
    op.drop_constraint("ck_repayment_drafts_original_amount_minor_money_bounds", "repayment_drafts", type_="check")
    op.drop_constraint("ck_repayment_drafts_amount_cents_money_bounds", "repayment_drafts", type_="check")
    op.create_check_constraint("ck_repayment_drafts_amount_cents_money_bounds", "repayment_drafts",
        "amount_cents BETWEEN 1 AND 9000000000000")
    op.alter_column("repayment_drafts", "amount_cents", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("repayment_drafts", "original_amount_minor")
    op.drop_column("repayment_drafts", "original_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("repayment_drafts")}
    for name in ("amount_cents", "original_amount_minor"):
        column = columns.get(name)
        if column is None or not isinstance(column["type"], sa.BigInteger) or not column["nullable"] or column["default"] is not None:
            raise RuntimeError("repayment capture amount must be nullable int8 without an invented default")
    code = columns.get("original_currency_code")
    if code is None or not isinstance(code["type"], sa.String) or code["type"].length != 3 or code["default"] is not None:
        raise RuntimeError("repayment capture currency is missing or implicitly defaulted")
    expected = {"ck_repayment_drafts_captured_money", "ck_repayment_drafts_amount_cents_money_bounds",
        "ck_repayment_drafts_original_amount_minor_money_bounds"}
    if not expected <= {check["name"] for check in inspector.get_check_constraints("repayment_drafts")}:
        raise RuntimeError("repayment capture money constraints are missing")
