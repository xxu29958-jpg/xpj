"""Manual rate corrections carry an optimistic concurrency version."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0004"
down_revision = "20260909_0003"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the manual rate version migration edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("exchange_rates", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_exchange_rates_row_version_positive", "exchange_rates", "row_version >= 1")
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM exchange_rates WHERE row_version > 1)")) or bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM api_idempotency_keys WHERE operation = 'set_exchange_rate')"
    )):
        raise RuntimeError("cannot erase accepted manual rate versions")
    op.drop_constraint("ck_exchange_rates_row_version_positive", "exchange_rates", type_="check")
    op.drop_column("exchange_rates", "row_version")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((col for col in inspector.get_columns("exchange_rates") if col["name"] == "row_version"), None)
    if column is None or not isinstance(column["type"], sa.Integer) or column["nullable"] or column["default"] is None:
        raise RuntimeError("manual rate version is missing or nullable")
    if "ck_exchange_rates_row_version_positive" not in {
        check["name"] for check in inspector.get_check_constraints("exchange_rates")
    }:
        raise RuntimeError("manual rate version constraint is missing")
