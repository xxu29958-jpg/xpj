"""Retain saved keywords and categories without changing existing queries or bills."""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0001"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the saved-search edge")


def upgrade():
    op.add_column("saved_views", sa.Column("query_text", sa.String(80), nullable=False, server_default=""))
    op.add_column("saved_views", sa.Column("category", sa.String(64), nullable=False, server_default=""))
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    has_conditions = bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM saved_views "
        "WHERE query_text <> '' OR category <> '')"))
    has_receipts = bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM api_idempotency_keys "
        "WHERE operation IN ('create_saved_view', 'update_saved_view') AND "
        "(COALESCE(response_body->>'query_text', '') <> '' OR COALESCE(response_body->>'category', '') <> ''))"))
    if has_conditions or has_receipts:
        raise RuntimeError("cannot erase saved search conditions or accepted receipts")
    op.drop_column("saved_views", "category")
    op.drop_column("saved_views", "query_text")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("saved_views")}
    for name, length in (("query_text", 80), ("category", 64)):
        column = columns.get(name)
        if column is None or column["nullable"] or not isinstance(column["type"], sa.String) or column["type"].length != length:
            raise RuntimeError("saved search conditions are not retained")
