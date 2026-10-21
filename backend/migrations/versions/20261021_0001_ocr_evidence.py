"""Preserve immutable image OCR blocks and exact model provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0001"
down_revision = "20261019_0005"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the OCR evidence migration edge")


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ocr_facts")}
    if "evidence_json" not in columns:
        op.add_column("ocr_facts", sa.Column("evidence_json", sa.Text(), nullable=True))
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ocr_facts WHERE evidence_json IS NOT NULL)")):
        raise RuntimeError("cannot downgrade while OCR image evidence exists")
    op.drop_column("ocr_facts", "evidence_json")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("ocr_facts")}
    evidence = columns.get("evidence_json")
    if evidence is None or not evidence["nullable"] or not isinstance(evidence["type"], sa.Text):
        raise RuntimeError("nullable OCR image evidence column is missing")
    live_revision = bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_revision = revision if live_revision == down_revision else live_revision
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != expected_revision:
        raise RuntimeError("dataset authority is not aligned with OCR evidence schema")
