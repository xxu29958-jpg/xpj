"""Preserve native CSV event review and ledger-local import receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_0001"
down_revision = "20260912_0001"
branch_labels = None
depends_on = None

_LEGACY_STATUSES = "'valid', 'error', 'applying', 'applied', 'insert_failed'"
_EVENT_COLUMNS = (
    "entry_kind", "offset_kind", "source_event_public_id", "source_root_public_id",
    "accounting_date", "stream_amount_cents", "lineage_status", "lineage_home_net_cents",
    "event_input", "review_reason",
)
# Frozen on this schema edge; the C07 v1 canonical-money manifest is unchanged.
_PROJECTION_MAX = 9_007_199_254_740_991
_PROJECTION_CHECKS = (
    ("stream_amount_cents", "ck_csv_import_rows_stream_amount_cents_projection_bounds"),
    ("lineage_home_net_cents", "ck_csv_import_rows_lineage_home_net_cents_projection_bounds"),
)


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the CSV financial-event edge")


def upgrade():
    bind = op.get_bind()
    # Ordinary saved rows gain no invented source identity or financial event.
    for column in (
        sa.Column("entry_kind", sa.String(32), server_default="expense", nullable=False),
        sa.Column("offset_kind", sa.String(32), nullable=True),
        sa.Column("source_event_public_id", sa.String(36), nullable=True),
        sa.Column("source_root_public_id", sa.String(36), nullable=True),
        sa.Column("accounting_date", sa.Date(), nullable=True),
        sa.Column("stream_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("lineage_status", sa.String(32), nullable=True),
        sa.Column("lineage_home_net_cents", sa.BigInteger(), nullable=True),
        sa.Column("event_input", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
    ):
        op.add_column("csv_import_rows", column)
    for column, name in _PROJECTION_CHECKS:
        op.create_check_constraint(name, "csv_import_rows", f"{column} BETWEEN {-_PROJECTION_MAX} AND {_PROJECTION_MAX}")
    op.drop_constraint("ck_csv_import_rows_status_valid", "csv_import_rows", type_="check")
    op.create_check_constraint(
        "ck_csv_import_rows_status_valid", "csv_import_rows",
        f"status IN ({_LEGACY_STATUSES}, 'review', 'matched', 'conflict')",
    )
    op.create_unique_constraint("uq_csv_import_rows_id_tenant", "csv_import_rows", ["id", "tenant_id"])
    op.create_index(
        "ix_csv_import_rows_source_event", "csv_import_rows",
        ["tenant_id", "entry_kind", "source_event_public_id"],
    )
    op.create_table(
        "csv_import_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("entry_kind", sa.String(32), nullable=False),
        sa.Column("source_event_public_id", sa.String(36), nullable=False),
        sa.Column("source_row_id", sa.Integer(), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("offset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "entry_kind", "source_event_public_id", name="uq_csv_import_events_source"),
        sa.CheckConstraint("entry_kind IN ('expense', 'offset')", name="ck_csv_import_events_kind"),
        sa.CheckConstraint(
            "offset_id IS NULL OR (entry_kind = 'offset' AND expense_id IS NOT NULL)",
            name="ck_csv_import_events_result",
        ),
        sa.CheckConstraint(
            "source_row_id IS NOT NULL OR (entry_kind = 'expense' AND expense_id IS NOT NULL AND offset_id IS NULL)",
            name="ck_csv_import_events_source",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id", "tenant_id"], ["csv_import_rows.id", "csv_import_rows.tenant_id"],
            name="fk_csv_import_events_source_row",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_csv_import_events_expense",
        ),
        sa.ForeignKeyConstraint(
            ["offset_id", "tenant_id"], ["expense_offset_facts.id", "expense_offset_facts.tenant_id"],
            name="fk_csv_import_events_offset",
        ),
    )
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    # Even malformed/unfinished native rows own input which the parent cannot read.
    native_rows = " OR ".join(
        ["entry_kind <> 'expense'", "status IN ('review', 'matched', 'conflict')"]
        + [f"{column} IS NOT NULL" for column in _EVENT_COLUMNS if column != "entry_kind"]
    )
    if bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM csv_import_events) "
        f"OR EXISTS (SELECT 1 FROM csv_import_rows WHERE {native_rows})"
    )):
        raise RuntimeError("cannot erase native CSV financial-event continuation")
    op.drop_table("csv_import_events")
    op.drop_index("ix_csv_import_rows_source_event", table_name="csv_import_rows")
    op.drop_constraint("uq_csv_import_rows_id_tenant", "csv_import_rows", type_="unique")
    op.drop_constraint("ck_csv_import_rows_status_valid", "csv_import_rows", type_="check")
    op.create_check_constraint(
        "ck_csv_import_rows_status_valid", "csv_import_rows", f"status IN ({_LEGACY_STATUSES})",
    )
    for _column, name in _PROJECTION_CHECKS:
        op.drop_constraint(name, "csv_import_rows", type_="check")
    for column in reversed(_EVENT_COLUMNS):
        op.drop_column("csv_import_rows", column)
    _set_authority_revision(bind, revision, down_revision)


def _assert_csv_row_shape(inspector):
    columns = {column["name"]: column for column in inspector.get_columns("csv_import_rows")}
    if set(_EVENT_COLUMNS) - columns.keys() or columns["entry_kind"]["nullable"]:
        raise RuntimeError("native CSV row evidence is missing")
    for column, _name in _PROJECTION_CHECKS:
        shape = columns[column]
        if not isinstance(shape["type"], sa.BigInteger) or not shape["nullable"] or shape["default"] is not None:
            raise RuntimeError("native CSV aggregate projection shape is invalid")


def _assert_csv_row_checks(inspector):
    checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints("csv_import_rows")}
    statuses = checks.get("ck_csv_import_rows_status_valid", "")
    if any(f"'{status}'" not in statuses for status in ("review", "matched", "conflict")):
        raise RuntimeError("native CSV review states are missing")
    if {name for _column, name in _PROJECTION_CHECKS} - checks.keys():
        raise RuntimeError("native CSV aggregate projection bounds are missing")


def _assert_csv_event_receipts(inspector):
    if not inspector.has_table("csv_import_events"):
        raise RuntimeError("ledger-local CSV event receipts are missing")
    checks = {item["name"] for item in inspector.get_check_constraints("csv_import_events")}
    if {"ck_csv_import_events_kind", "ck_csv_import_events_result", "ck_csv_import_events_source"} - checks:
        raise RuntimeError("CSV event receipt shape constraints are missing")
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("csv_import_events")}
    if ("tenant_id", "entry_kind", "source_event_public_id") not in uniques:
        raise RuntimeError("CSV source event uniqueness is missing")
    foreign_keys = {
        (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
        for item in inspector.get_foreign_keys("csv_import_events")
    }
    for source, target in (
        ("source_row_id", "csv_import_rows"), ("expense_id", "expenses"), ("offset_id", "expense_offset_facts"),
    ):
        if ((source, "tenant_id"), target, ("id", "tenant_id")) not in foreign_keys:
            raise RuntimeError("CSV event receipt ledger isolation is missing")


def _assert_csv_row_indexes(inspector):
    indexes = inspector.get_indexes("csv_import_rows")
    if not any(item["column_names"] == ["tenant_id", "entry_kind", "source_event_public_id"] for item in indexes):
        raise RuntimeError("native CSV source lookup is missing")
    if not any(item["unique"] and item["column_names"] == ["tenant_id", "expense_id"] for item in indexes):
        raise RuntimeError("original CSV inserted-expense uniqueness is missing")


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    _assert_csv_row_shape(inspector)
    _assert_csv_row_checks(inspector)
    _assert_csv_event_receipts(inspector)
    _assert_csv_row_indexes(inspector)
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with CSV financial events")
