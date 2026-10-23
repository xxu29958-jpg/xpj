"""Preserve original notification field fragments without changing legacy financial facts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261023_0002"
down_revision = "20261023_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the notification field migration edge")


def upgrade():
    bind = op.get_bind()
    if "field_evidence" not in {item["name"] for item in sa.inspect(bind).get_columns("payment_captures")}:
        op.add_column("payment_captures", sa.Column("field_evidence", JSONB(), nullable=True))
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM payment_captures WHERE field_evidence IS NOT NULL)")):
        raise RuntimeError("cannot downgrade while notification field evidence exists")
    op.drop_column("payment_captures", "field_evidence")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {item["name"]: item for item in sa.inspect(bind).get_columns("payment_captures")}
    evidence = columns.get("field_evidence")
    if evidence is None or not evidence["nullable"] or not isinstance(evidence["type"], JSONB):
        raise RuntimeError("nullable notification field evidence is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != (revision if live == down_revision else live):
        raise RuntimeError("dataset authority is not aligned with notification field evidence")
