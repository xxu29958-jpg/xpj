"""Freeze repayment time intent without inventing historical precision or dates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261011_0001"
down_revision = "20261008_0001"
branch_labels = None
depends_on = None

_PAYMENTS = ("repayments", "member_repayment_proposals")
_TABLES = (*_PAYMENTS, "repayment_drafts")
_TIME_SHAPE = (
    "((accounting_time_snapshot IS NULL AND paid_at IS NOT NULL) OR "
    "(jsonb_typeof(accounting_time_snapshot) = 'object' "
    "AND accounting_time_snapshot->>'precision' IN ('instant', 'date_only', 'unknown') "
    "AND paid_at IS NOT DISTINCT FROM (accounting_time_snapshot->>'instant_utc')::timestamptz "
    "AND (accounting_time_snapshot->>'precision' <> 'date_only' OR paid_at IS NULL) "
    "AND (accounting_time_snapshot->>'precision' <> 'instant' OR paid_at IS NOT NULL))) IS TRUE"
)


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the repayment-time edge")


def upgrade():
    for table in _TABLES:
        op.add_column(table, sa.Column("accounting_time_snapshot", JSONB(none_as_null=True), nullable=True))
    for table in _PAYMENTS:
        op.alter_column(table, "paid_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        op.create_check_constraint(f"ck_{table}_payment_time", table, _TIME_SHAPE)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    for table in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE accounting_time_snapshot IS NOT NULL)")):
            raise RuntimeError("cannot erase original repayment time evidence")
    for table in _PAYMENTS:
        op.drop_constraint(f"ck_{table}_payment_time", table, type_="check")
        op.alter_column(table, "paid_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    for table in reversed(_TABLES):
        op.drop_column(table, "accounting_time_snapshot")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table in _TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        snapshot = columns.get("accounting_time_snapshot")
        if snapshot is None or not isinstance(snapshot["type"], JSONB) or not snapshot["nullable"] or snapshot["default"] is not None:
            raise RuntimeError("repayment time evidence must be nullable JSONB without an invented default")
        if table in _PAYMENTS:
            if not columns["paid_at"]["nullable"]:
                raise RuntimeError("date-only repayment must not require an invented instant")
            names = {check["name"] for check in inspector.get_check_constraints(table)}
            if f"ck_{table}_payment_time" not in names:
                raise RuntimeError("repayment time evidence does not constrain the legacy instant")
