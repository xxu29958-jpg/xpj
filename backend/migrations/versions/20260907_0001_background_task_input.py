"""Persist original input for receipt-driven enrichment continuation."""

import sqlalchemy as sa
from alembic import op

revision = "20260907_0001"
down_revision = "20260906_0002"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    updated = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the task input migration edge")


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("background_tasks")}
    if "input_payload_json" not in columns:
        op.add_column("background_tasks", sa.Column("input_payload_json", sa.Text(), nullable=True))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM background_tasks WHERE input_payload_json IS NOT NULL)")):
        raise RuntimeError("cannot downgrade while original task input exists")
    op.drop_column("background_tasks", "input_payload_json")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("background_tasks")}
    payload = columns.get("input_payload_json")
    if payload is None or not payload["nullable"] or not isinstance(payload["type"], sa.Text):
        raise RuntimeError("nullable original task input column is missing")
    live_revision = bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_revision = revision if live_revision == down_revision else live_revision
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if authority != expected_revision:
        raise RuntimeError("dataset authority is not aligned with task input schema")
