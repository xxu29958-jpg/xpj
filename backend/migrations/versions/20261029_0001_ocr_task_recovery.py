"""Preserve bounded OCR recovery attempts on the original durable task."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_0001"
down_revision = "20261028_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the OCR recovery migration edge")


def upgrade():
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("background_tasks")}
    columns = [sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_history_json", sa.Text(), nullable=False, server_default="[]")]
    for column in columns:
        if column.name not in existing:
            op.add_column("background_tasks", column)
    constraints = {item["name"] for item in sa.inspect(bind).get_check_constraints("background_tasks")}
    if "ck_background_tasks_recovery_non_negative" not in constraints:
        op.create_check_constraint("ck_background_tasks_recovery_non_negative", "background_tasks", "recovery_attempts >= 0")
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM background_tasks WHERE recovery_attempts <> 0 "
                          "OR recovery_after IS NOT NULL OR recovery_history_json <> '[]')")):
        raise RuntimeError("cannot erase retained OCR recovery attempts")
    op.drop_constraint("ck_background_tasks_recovery_non_negative", "background_tasks", type_="check")
    for name in ("recovery_after", "recovery_history_json", "recovery_attempts"):
        op.drop_column("background_tasks", name)
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {item["name"]: item for item in inspector.get_columns("background_tasks")}
    for name, kind, nullable in (("recovery_attempts", sa.Integer, False),
                                ("recovery_history_json", sa.Text, False), ("recovery_after", sa.DateTime, True)):
        column = columns.get(name)
        if column is None or column["nullable"] != nullable or not isinstance(column["type"], kind):
            raise RuntimeError("OCR recovery attempt columns are missing or incompatible")
    if "ck_background_tasks_recovery_non_negative" not in {
        item["name"] for item in inspector.get_check_constraints("background_tasks")
    }:
        raise RuntimeError("OCR recovery attempt constraint is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != (revision if live == down_revision else live):
        raise RuntimeError("dataset authority is not aligned with OCR recovery evidence")
