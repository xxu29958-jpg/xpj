"""Dated reference coverage and directly queryable original expense tasks."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0001"
down_revision = "20260909_0005"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    updated = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the FX continuation edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("fx_rates", sa.Column("verified_through", sa.Date(), nullable=True))
    op.create_check_constraint("ck_fx_rates_coverage_date", "fx_rates",
        "verified_through IS NULL OR verified_through >= rate_date")
    op.add_column("background_tasks", sa.Column("source_expense_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_background_tasks_source_expense", "background_tasks", "expenses",
        ["source_expense_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_background_tasks_source_expense_id", "background_tasks", ["source_expense_id"])
    # Source navigation is derived only from a valid original in the same ledger.
    # Old rates retain their published day; no historical range is invented.
    bind.execute(sa.text("""
        WITH originals AS (
            SELECT id, tenant_id,
                CASE WHEN input_payload_json IS JSON OBJECT
                    THEN input_payload_json::jsonb END AS payload
            FROM background_tasks WHERE task_type = 'expense_enrichment'
        )
        UPDATE background_tasks AS task SET source_expense_id = expense.id
        FROM originals, expenses AS expense
        WHERE task.id = originals.id AND expense.tenant_id = originals.tenant_id
          AND originals.payload ->> 'tenant_id' = originals.tenant_id
          AND jsonb_typeof(originals.payload -> 'expense_id') = 'number'
          AND originals.payload ->> 'expense_id' = expense.id::text
    """))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM background_tasks WHERE task_type = 'expense_fx')")):
        raise RuntimeError("cannot remove original foreign-bill task continuation")
    op.drop_index("ix_background_tasks_source_expense_id", table_name="background_tasks")
    op.drop_constraint("fk_background_tasks_source_expense", "background_tasks", type_="foreignkey")
    op.drop_column("background_tasks", "source_expense_id")
    op.drop_constraint("ck_fx_rates_coverage_date", "fx_rates", type_="check")
    op.drop_column("fx_rates", "verified_through")
    _set_authority_revision(bind, revision, down_revision)


def _assert_rate_coverage_schema(inspector):
    rates = {column["name"]: column for column in inspector.get_columns("fx_rates")}
    if "verified_through" not in rates or not rates["verified_through"]["nullable"]:
        raise RuntimeError("nullable historical FX coverage is missing")
    if not isinstance(rates["verified_through"]["type"], sa.Date):
        raise RuntimeError("historical FX coverage is not a date")
    if not any(check["name"] == "ck_fx_rates_coverage_date" for check in inspector.get_check_constraints("fx_rates")):
        raise RuntimeError("historical FX coverage constraint is missing")


def _assert_expense_task_schema(inspector):
    tasks = {column["name"]: column for column in inspector.get_columns("background_tasks")}
    if "source_expense_id" not in tasks or not tasks["source_expense_id"]["nullable"]:
        raise RuntimeError("original expense task source is missing")
    if not isinstance(tasks["source_expense_id"]["type"], sa.Integer):
        raise RuntimeError("original expense task source is not an integer")
    indexes = inspector.get_indexes("background_tasks")
    if not any(index["column_names"] == ["source_expense_id"] for index in indexes):
        raise RuntimeError("original expense task source index is missing")
    sources = inspector.get_foreign_keys("background_tasks")
    if not any(fk["constrained_columns"] == ["source_expense_id"] and fk["referred_table"] == "expenses"
               and fk["referred_columns"] == ["id"] and fk.get("options", {}).get("ondelete") == "SET NULL"
               for fk in sources):
        raise RuntimeError("original expense source deletion boundary is missing")


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    _assert_rate_coverage_schema(inspector)
    _assert_expense_task_schema(inspector)
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with FX continuation")
