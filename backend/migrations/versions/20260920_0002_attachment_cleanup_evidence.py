"""Persist bounded attachment cleanup intent without inferring historical evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260920_0002"
down_revision = "20260920_0001"
branch_labels = None
depends_on = None

# Frozen migration contract; future runtime models must not rewrite this edge.
_CHECK_SQL = r"""attachment_cleanup_request IS NULL OR COALESCE(
    CASE WHEN jsonb_typeof(attachment_cleanup_request) = 'object' THEN
        attachment_cleanup_request ?& ARRAY['request_id', 'reason', 'requested_at', 'image', 'thumbnail']
        AND attachment_cleanup_request - ARRAY['request_id', 'reason', 'requested_at', 'image', 'thumbnail'] = '{}'::jsonb
        AND jsonb_typeof(attachment_cleanup_request -> 'request_id') = 'string'
        AND attachment_cleanup_request ->> 'request_id' ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        AND attachment_cleanup_request ->> 'reason' IN ('after_confirm', 'confirmed_retention', 'rejected_retention')
        AND jsonb_typeof(attachment_cleanup_request -> 'requested_at') = 'string'
        AND attachment_cleanup_request ->> 'requested_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
        AND (attachment_cleanup_request -> 'image' <> 'null'::jsonb
             OR attachment_cleanup_request -> 'thumbnail' <> 'null'::jsonb)
        AND (CASE WHEN (attachment_cleanup_request -> 'image') = 'null'::jsonb THEN TRUE
        WHEN jsonb_typeof((attachment_cleanup_request -> 'image')) = 'object' THEN
            (attachment_cleanup_request -> 'image') ?& ARRAY['reference', 'outcome', 'completed_at', 'error_code']
            AND (attachment_cleanup_request -> 'image') - ARRAY['reference', 'outcome', 'completed_at', 'error_code'] = '{}'::jsonb
            AND jsonb_typeof((attachment_cleanup_request -> 'image') -> 'reference') = 'string'
            AND char_length((attachment_cleanup_request -> 'image') ->> 'reference') BETWEEN 1 AND 500
            AND (attachment_cleanup_request -> 'image') ->> 'outcome' IN ('pending', 'deleted', 'cancelled')
            AND CASE WHEN (attachment_cleanup_request -> 'image') ->> 'outcome' = 'pending' THEN
                (attachment_cleanup_request -> 'image') -> 'completed_at' = 'null'::jsonb
                AND ((attachment_cleanup_request -> 'image') -> 'error_code' = 'null'::jsonb
                     OR (attachment_cleanup_request -> 'image') ->> 'error_code' IN ('unlink_failed', 'invalid_reference'))
            ELSE jsonb_typeof((attachment_cleanup_request -> 'image') -> 'completed_at') = 'string'
                AND (attachment_cleanup_request -> 'image') ->> 'completed_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                AND (attachment_cleanup_request -> 'image') -> 'error_code' = 'null'::jsonb END
        ELSE FALSE END) AND (CASE WHEN (attachment_cleanup_request -> 'thumbnail') = 'null'::jsonb THEN TRUE
        WHEN jsonb_typeof((attachment_cleanup_request -> 'thumbnail')) = 'object' THEN
            (attachment_cleanup_request -> 'thumbnail') ?& ARRAY['reference', 'outcome', 'completed_at', 'error_code']
            AND (attachment_cleanup_request -> 'thumbnail') - ARRAY['reference', 'outcome', 'completed_at', 'error_code'] = '{}'::jsonb
            AND jsonb_typeof((attachment_cleanup_request -> 'thumbnail') -> 'reference') = 'string'
            AND char_length((attachment_cleanup_request -> 'thumbnail') ->> 'reference') BETWEEN 1 AND 500
            AND (attachment_cleanup_request -> 'thumbnail') ->> 'outcome' IN ('pending', 'deleted', 'cancelled')
            AND CASE WHEN (attachment_cleanup_request -> 'thumbnail') ->> 'outcome' = 'pending' THEN
                (attachment_cleanup_request -> 'thumbnail') -> 'completed_at' = 'null'::jsonb
                AND ((attachment_cleanup_request -> 'thumbnail') -> 'error_code' = 'null'::jsonb
                     OR (attachment_cleanup_request -> 'thumbnail') ->> 'error_code' IN ('unlink_failed', 'invalid_reference'))
            ELSE jsonb_typeof((attachment_cleanup_request -> 'thumbnail') -> 'completed_at') = 'string'
                AND (attachment_cleanup_request -> 'thumbnail') ->> 'completed_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                AND (attachment_cleanup_request -> 'thumbnail') -> 'error_code' = 'null'::jsonb END
        ELSE FALSE END)
    ELSE FALSE END, FALSE)"""
_CHECK_NAME = "ck_expenses_attachment_cleanup_request"


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"target": target, "expected": expected})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the attachment cleanup edge")


def upgrade():
    op.add_column("expenses", sa.Column("attachment_cleanup_request", JSONB(none_as_null=True), nullable=True))
    op.add_column("expenses", sa.Column("image_replenished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(_CHECK_NAME, "expenses", _CHECK_SQL)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM expenses WHERE attachment_cleanup_request IS NOT NULL "
        "OR image_replenished_at IS NOT NULL)"
    )):
        raise RuntimeError("cannot discard attachment cleanup or replenishment evidence")
    op.drop_constraint(_CHECK_NAME, "expenses", type_="check")
    op.drop_column("expenses", "image_replenished_at")
    op.drop_column("expenses", "attachment_cleanup_request")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("expenses")}
    for name in ("attachment_cleanup_request", "image_replenished_at"):
        column = columns.get(name)
        if column is None or not column["nullable"] or column["default"] is not None:
            raise RuntimeError("nullable attachment cleanup evidence is missing")
    if not isinstance(columns["attachment_cleanup_request"]["type"], JSONB):
        raise RuntimeError("attachment cleanup evidence must use JSONB")
    timestamp = columns["image_replenished_at"]["type"]
    if not isinstance(timestamp, sa.DateTime) or not timestamp.timezone:
        raise RuntimeError("attachment replenishment evidence must be timezone-aware")
    if _CHECK_NAME not in {item["name"] for item in inspector.get_check_constraints("expenses")}:
        raise RuntimeError("closed attachment cleanup request constraint is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with attachment cleanup")
