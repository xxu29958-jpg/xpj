"""Preserve principal occurrence separately from when a Debt was recorded."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261012_0001"
down_revision = "20261011_0001"
branch_labels = None
depends_on = None

_TIME_SHAPE = (
    "(accounting_time_snapshot IS NULL OR (jsonb_typeof(accounting_time_snapshot) = 'object' "
    "AND accounting_time_snapshot->>'precision' IN ('instant', 'date_only', 'unknown') "
    "AND (accounting_time_snapshot->>'precision' <> 'date_only' OR "
    "(accounting_time_snapshot->>'instant_utc' IS NULL "
    "AND accounting_time_snapshot->>'user_local_date' IS NOT NULL)) "
    "AND (accounting_time_snapshot->>'precision' <> 'instant' "
    "OR accounting_time_snapshot->>'instant_utc' IS NOT NULL))) IS TRUE"
)


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the principal-time edge")


def upgrade():
    op.add_column("debts", sa.Column("accounting_time_snapshot", JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint("ck_debts_principal_time", "debts", _TIME_SHAPE)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM debts WHERE accounting_time_snapshot IS NOT NULL)")):
        raise RuntimeError("cannot erase original principal time evidence")
    op.drop_constraint("ck_debts_principal_time", "debts", type_="check")
    op.drop_column("debts", "accounting_time_snapshot")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((item for item in inspector.get_columns("debts") if item["name"] == "accounting_time_snapshot"), None)
    if column is None or not isinstance(column["type"], JSONB) or not column["nullable"] or column["default"] is not None:
        raise RuntimeError("principal time evidence must be nullable JSONB without an invented default")
    if "ck_debts_principal_time" not in {check["name"] for check in inspector.get_check_constraints("debts")}:
        raise RuntimeError("principal time evidence shape is not constrained")
