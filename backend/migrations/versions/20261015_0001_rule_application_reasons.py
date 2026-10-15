"""Retain the user's reasons on the original rule application batch."""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0001"
down_revision = "20261014_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the rule reason migration edge")


def upgrade():
    for name in ("application_reason", "rollback_reason"):
        op.add_column("rule_application_batches", sa.Column(name, sa.String(500), nullable=True))
    _set_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM rule_application_batches "
        "WHERE application_reason IS NOT NULL OR rollback_reason IS NOT NULL)")):
        raise RuntimeError("cannot erase retained rule application reasons")
    op.drop_column("rule_application_batches", "rollback_reason")
    op.drop_column("rule_application_batches", "application_reason")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {item["name"]: item for item in sa.inspect(bind).get_columns("rule_application_batches")}
    for name in ("application_reason", "rollback_reason"):
        column = columns.get(name)
        if (column is None or not isinstance(column["type"], sa.String) or column["type"].length != 500
            or not column["nullable"] or column["default"] is not None):
            raise RuntimeError("rule reasons must be nullable text without an invented historical reason")
