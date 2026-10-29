"""Keep the current OCR attempt's configured and observed execution identities."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_0002"
down_revision = "20261029_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the OCR execution context migration edge")


def upgrade():
    bind = op.get_bind()
    if "execution_context_json" not in {item["name"] for item in sa.inspect(bind).get_columns("background_tasks")}:
        op.add_column("background_tasks", sa.Column("execution_context_json", sa.Text(), nullable=True))
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM background_tasks WHERE execution_context_json IS NOT NULL)")):
        raise RuntimeError("cannot erase retained OCR execution context")
    op.drop_column("background_tasks", "execution_context_json")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    column = next((item for item in sa.inspect(bind).get_columns("background_tasks")
        if item["name"] == "execution_context_json"), None)
    if column is None or not column["nullable"] or not isinstance(column["type"], sa.Text):
        raise RuntimeError("OCR execution context column is missing or incompatible")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != (revision if live == down_revision else live):
        raise RuntimeError("dataset authority is not aligned with OCR execution context")
