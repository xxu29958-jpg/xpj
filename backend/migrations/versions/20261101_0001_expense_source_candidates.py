"""Preserve independent event identity and provenance for multi-transaction sources."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261101_0001"
down_revision = "20261029_0002"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the source candidate migration edge")


def upgrade():
    bind = op.get_bind()
    if "expense_source_candidates" not in sa.inspect(bind).get_table_names():
        op.create_table("expense_source_candidates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("source_expense_id", sa.Integer(), nullable=False),
            sa.Column("expense_id", sa.Integer(), nullable=False),
            sa.Column("event_key", sa.String(64), nullable=False),
            sa.Column("extraction_hash", sa.String(64), nullable=False),
            sa.Column("event_index", sa.Integer(), nullable=False),
            sa.Column("evidence", JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["source_expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
                name="fk_expense_source_candidate_source", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
                name="fk_expense_source_candidate_target", ondelete="RESTRICT"),
            sa.UniqueConstraint("tenant_id", "source_expense_id", "event_key", name="uq_expense_source_candidate_event"),
            sa.UniqueConstraint("tenant_id", "expense_id", name="uq_expense_source_candidate_target"),
            sa.CheckConstraint("event_index >= 0", name="ck_expense_source_candidate_index"))
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM expense_source_candidates)")):
        raise RuntimeError("cannot erase retained transaction source candidates")
    op.drop_table("expense_source_candidates")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {item["name"]: item for item in inspector.get_columns("expense_source_candidates")}
    expected = {"id", "tenant_id", "source_expense_id", "expense_id", "event_key", "extraction_hash", "event_index", "evidence", "created_at"}
    if set(columns) != expected or any(item["nullable"] for item in columns.values()) or not isinstance(columns["evidence"]["type"], JSONB):
        raise RuntimeError("source candidate evidence schema is missing or incompatible")
    constraints = {item["name"] for item in inspector.get_unique_constraints("expense_source_candidates")}
    if constraints != {"uq_expense_source_candidate_event", "uq_expense_source_candidate_target"}:
        raise RuntimeError("source candidate identity constraints are missing")
    foreign_keys = inspector.get_foreign_keys("expense_source_candidates")
    if len(foreign_keys) != 2 or any(item["referred_table"] != "expenses" or item["referred_columns"] != ["id", "tenant_id"]
            or item["options"].get("ondelete") != "RESTRICT" for item in foreign_keys):
        raise RuntimeError("source candidate ledger boundaries are missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1"))
    if authority != (revision if live == down_revision else live):
        raise RuntimeError("dataset authority is not aligned with source candidates")
