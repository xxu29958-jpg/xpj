"""Add confirmed Expense current-revision and append-only history.

Revision ID: 20260828_0001
Revises: 20260821_0001
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260828_0001"
down_revision = "20260821_0001"
branch_labels = None
depends_on = None

_TABLE = "expense_revisions"
_EXPENSE_CHECK = "ck_expenses_fact_revision_nonnegative"
_CURRENCY_BINDING_TABLE = "installation_currency_bindings"
_CURRENCY_WRITER_GUC = "xpj.currency_writer"
_IDEMPOTENCY_TABLE = "api_idempotency_keys"
_IDEMPOTENCY_RESPONSE_COLUMN = "response_body"
_REVISION_CHECKS = {
    "ck_expense_revisions_number_positive",
    "ck_expense_revisions_kind_valid",
    "ck_expense_revisions_reason_length",
    "ck_expense_revisions_before_shape",
    "ck_expense_revisions_resulting_row_version_positive",
    "ck_expense_revisions_actor_device_snapshot_pair",
}
_REVISION_COLUMNS = {
    "id",
    "public_id",
    "tenant_id",
    "expense_id",
    "revision_number",
    "change_kind",
    "reason",
    "idempotency_key",
    "actor_account_id",
    "actor_device_public_id",
    "actor_device_name",
    "changed_fields",
    "before_snapshot",
    "after_snapshot",
    "previous_row_version",
    "resulting_row_version",
    "created_at",
}
_SNAPSHOT_FIELDS = [
    "amount_cents",
    "home_currency_code",
    "original_currency_code",
    "original_amount_minor",
    "exchange_rate_to_cny",
    "exchange_rate_date",
    "exchange_rate_source",
    "fx_status",
    "merchant",
    "category",
    "note",
    "source",
    "tags",
    "value_score",
    "regret_score",
    "expense_time",
    "confirmed_at",
    "items_sum_status",
    "items",
    "splits",
]


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _add_projection_column(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("expenses")}
    if "fact_revision" not in columns:
        op.add_column(
            "expenses",
            sa.Column(
                "fact_revision",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    checks = {
        check["name"] for check in sa.inspect(bind).get_check_constraints("expenses")
    }
    if _EXPENSE_CHECK not in checks:
        op.create_check_constraint(
            _EXPENSE_CHECK,
            "expenses",
            "fact_revision >= 0",
        )


def _add_idempotency_response_column(bind: sa.Connection) -> None:
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns(_IDEMPOTENCY_TABLE)
    }
    if _IDEMPOTENCY_RESPONSE_COLUMN not in columns:
        op.add_column(
            _IDEMPOTENCY_TABLE,
            sa.Column(_IDEMPOTENCY_RESPONSE_COLUMN, sa.JSON(), nullable=True),
        )


def _create_revision_table(bind: sa.Connection) -> None:
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("actor_device_public_id", sa.String(length=36), nullable=True),
        sa.Column("actor_device_name", sa.String(length=120), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("previous_row_version", sa.Integer(), nullable=True),
        sa.Column("resulting_row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_expense_revisions_number_positive",
        ),
        sa.CheckConstraint(
            "change_kind IN ('confirmed', 'correction')",
            name="ck_expense_revisions_kind_valid",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_revisions_reason_length",
        ),
        sa.CheckConstraint(
            "(change_kind = 'confirmed' AND before_snapshot IS NULL) OR "
            "(change_kind = 'correction' AND before_snapshot IS NOT NULL)",
            name="ck_expense_revisions_before_shape",
        ),
        sa.CheckConstraint(
            "resulting_row_version >= 1",
            name="ck_expense_revisions_resulting_row_version_positive",
        ),
        sa.CheckConstraint(
            "(actor_device_public_id IS NULL) = (actor_device_name IS NULL)",
            name="ck_expense_revisions_actor_device_snapshot_pair",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["accounts.id"],
            name="fk_expense_revisions_actor_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_revisions_expense_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "expense_id",
            "revision_number",
            name="uq_expense_revisions_expense_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_expense_revisions_idempotency_key",
        ),
    )
    op.create_index(
        "ix_expense_revisions_tenant_expense_revision",
        _TABLE,
        ["tenant_id", "expense_id", "revision_number"],
        unique=False,
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION ticketbox_reject_expense_revision_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'expense_revisions is append-only' USING ERRCODE = '55000'; "
        "END $$"
    )
    op.execute(
        "CREATE TRIGGER trg_expense_revisions_append_only "
        "BEFORE UPDATE OR DELETE ON expense_revisions FOR EACH ROW "
        "EXECUTE FUNCTION ticketbox_reject_expense_revision_mutation()"
    )
    op.create_index(
        "ix_expense_revisions_actor_created",
        _TABLE,
        ["actor_account_id", "created_at"],
        unique=False,
    )


def _backfill_confirmed_baselines(bind: sa.Connection) -> None:
    expenses = bind.execute(
        sa.text(
            "SELECT id, tenant_id, amount_cents, home_currency_code, "
            "original_currency_code, original_amount_minor, exchange_rate_to_cny, "
            "exchange_rate_date, exchange_rate_source, fx_status, merchant, category, "
            "note, source, tags, value_score, regret_score, expense_time, confirmed_at, "
            "items_sum_status, row_version, created_at, updated_at "
            "FROM expenses WHERE confirmed_at IS NOT NULL ORDER BY id"
        )
    ).mappings().all()
    if not expenses:
        return
    ids = [row["id"] for row in expenses]
    items_by_expense: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in bind.execute(
        sa.text(
            "SELECT expense_id, position, kind, name, quantity_text, unit_price_cents, "
            "amount_cents, category, raw_text, confidence FROM expense_items "
            "WHERE expense_id = ANY(:ids) ORDER BY expense_id, position, id"
        ),
        {"ids": ids},
    ).mappings():
        expense_id = int(row["expense_id"])
        items_by_expense[expense_id].append(
            {key: _json_value(value) for key, value in row.items() if key != "expense_id"}
        )
    splits_by_expense: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in bind.execute(
        sa.text(
            "SELECT expense_id, position, member_id, amount_cents, note "
            "FROM expense_splits WHERE expense_id = ANY(:ids) "
            "ORDER BY expense_id, position, id"
        ),
        {"ids": ids},
    ).mappings():
        expense_id = int(row["expense_id"])
        splits_by_expense[expense_id].append(
            {key: _json_value(value) for key, value in row.items() if key != "expense_id"}
        )
    insert_sql = sa.text(
        "INSERT INTO expense_revisions "
        "(public_id, tenant_id, expense_id, revision_number, change_kind, reason, "
        "idempotency_key, actor_account_id, actor_device_public_id, actor_device_name, changed_fields, "
        "before_snapshot, after_snapshot, previous_row_version, resulting_row_version, created_at) "
        "SELECT CAST(:public_id AS varchar(36)), CAST(:tenant_id AS varchar(64)), "
        "CAST(:expense_id AS integer), 1, 'confirmed', '历史确认事实', "
        "NULL, NULL, NULL, NULL, CAST(:changed_fields AS json), NULL, CAST(:after_snapshot AS json), "
        "NULL, :row_version, :created_at "
        "WHERE NOT EXISTS (SELECT 1 FROM expense_revisions "
        "WHERE tenant_id = CAST(:tenant_id AS varchar(64)) "
        "AND expense_id = CAST(:expense_id AS integer))"
    )
    for row in expenses:
        expense_id = int(row["id"])
        snapshot = {
            field: _json_value(row[field])
            for field in _SNAPSHOT_FIELDS
            if field not in {"items", "splits"}
        }
        snapshot["items"] = items_by_expense[expense_id]
        snapshot["splits"] = splits_by_expense[expense_id]
        bind.execute(
            insert_sql,
            {
                "public_id": str(uuid4()),
                "tenant_id": row["tenant_id"],
                "expense_id": expense_id,
                "changed_fields": json.dumps(_SNAPSHOT_FIELDS, ensure_ascii=False),
                "after_snapshot": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                "row_version": row["row_version"],
                "created_at": row["confirmed_at"] or row["updated_at"] or row["created_at"],
            },
        )
    binding = bind.execute(
        sa.text(
            "SELECT state, currency_contract_version, binding_revision "
            f"FROM {_CURRENCY_BINDING_TABLE} WHERE singleton_id = 1 FOR SHARE"
        )
    ).mappings().one_or_none()
    if binding is None or binding["state"] != "ACTIVE":
        raise RuntimeError("confirmed expense backfill requires an active currency binding")
    bind.execute(
        sa.text("SELECT set_config(:key, :proof, true)"),
        {
            "key": _CURRENCY_WRITER_GUC,
            "proof": (
                f'{int(binding["currency_contract_version"])}:'
                f'{int(binding["binding_revision"])}'
            ),
        },
    )
    bind.execute(
        sa.text(
            "UPDATE expenses SET fact_revision = 1 "
            "WHERE confirmed_at IS NOT NULL AND fact_revision = 0"
        )
    )


def _set_dataset_authority_revision(
    bind: sa.Connection,
    *,
    expected_revision: str,
    target_revision: str,
) -> None:
    current = bind.scalar(
        sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")
    )
    if current == target_revision:
        return
    if current != expected_revision:
        raise RuntimeError("dataset authority revision is outside this migration edge")
    updated = bind.execute(
        sa.text(
            "UPDATE dataset_authority SET schema_revision = :target_revision "
            "WHERE singleton_id = 1 AND schema_revision = :expected_revision"
        ),
        {
            "expected_revision": expected_revision,
            "target_revision": target_revision,
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority revision update lost its migration claim")


def upgrade() -> None:
    bind = op.get_bind()
    _add_projection_column(bind)
    _add_idempotency_response_column(bind)
    _create_revision_table(bind)
    _backfill_confirmed_baselines(bind)
    _set_dataset_authority_revision(
        bind,
        expected_revision=down_revision,
        target_revision=revision,
    )
    assert_postcondition(bind)


def downgrade() -> None:
    bind = op.get_bind()
    idempotency_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns(_IDEMPOTENCY_TABLE)
    }
    if _IDEMPOTENCY_RESPONSE_COLUMN in idempotency_columns:
        has_aggregate_results = bind.scalar(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM {_IDEMPOTENCY_TABLE} "
                f"WHERE {_IDEMPOTENCY_RESPONSE_COLUMN} IS NOT NULL LIMIT 1)"
            )
        )
        if has_aggregate_results:
            raise RuntimeError(
                "cannot downgrade expense revisions while aggregate command results exist"
            )
    if sa.inspect(bind).has_table(_TABLE):
        has_financial_history = bind.scalar(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {_TABLE} LIMIT 1)")
        )
        if has_financial_history:
            raise RuntimeError(
                "cannot downgrade expense revisions while financial history exists"
            )
        op.drop_table(_TABLE)
    op.execute("DROP FUNCTION IF EXISTS ticketbox_reject_expense_revision_mutation()")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("expenses")}
    if "fact_revision" in columns:
        checks = {
            check["name"] for check in sa.inspect(bind).get_check_constraints("expenses")
        }
        if _EXPENSE_CHECK in checks:
            op.drop_constraint(_EXPENSE_CHECK, "expenses", type_="check")
        op.drop_column("expenses", "fact_revision")
    if _IDEMPOTENCY_RESPONSE_COLUMN in idempotency_columns:
        op.drop_column(_IDEMPOTENCY_TABLE, _IDEMPOTENCY_RESPONSE_COLUMN)
    _set_dataset_authority_revision(
        bind,
        expected_revision=revision,
        target_revision=down_revision,
    )


def assert_postcondition(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    expense_columns = {column["name"] for column in inspector.get_columns("expenses")}
    expense_checks = {
        check["name"] for check in inspector.get_check_constraints("expenses")
    }
    if "fact_revision" not in expense_columns or _EXPENSE_CHECK not in expense_checks:
        raise RuntimeError("expenses fact_revision projection is incomplete")
    idempotency_columns = {
        column["name"] for column in inspector.get_columns(_IDEMPOTENCY_TABLE)
    }
    if _IDEMPOTENCY_RESPONSE_COLUMN not in idempotency_columns:
        raise RuntimeError("aggregate command replay projection is incomplete")
    if not inspector.has_table(_TABLE):
        raise RuntimeError("expense_revisions table is missing")
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    checks = {check["name"] for check in inspector.get_check_constraints(_TABLE)}
    if columns != _REVISION_COLUMNS or checks != _REVISION_CHECKS:
        raise RuntimeError("expense_revisions schema is incomplete")
    trigger_exists = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_trigger "
            "WHERE tgname = 'trg_expense_revisions_append_only' "
            "AND tgrelid = 'expense_revisions'::regclass AND NOT tgisinternal)"
        )
    )
    if not trigger_exists:
        raise RuntimeError("expense_revisions append-only trigger is missing")
    missing = bind.scalar(
        sa.text(
            "SELECT count(*) FROM expenses e WHERE e.confirmed_at IS NOT NULL "
            "AND (e.fact_revision < 1 OR NOT EXISTS ("
            "SELECT 1 FROM expense_revisions r WHERE r.tenant_id = e.tenant_id "
            "AND r.expense_id = e.id AND r.revision_number = 1))"
        )
    )
    if missing:
        raise RuntimeError("confirmed expense baseline backfill is incomplete")
    authority_revision = bind.scalar(
        sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")
    )
    alembic_revision = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    # During this migration's own ``upgrade`` Alembic has not advanced its
    # version row yet, while the dataset-authority CAS already names this
    # revision. During a later release-head revalidation both rows name the
    # newer authorized head. Accept those two honest phases; the terminal
    # revision's postcondition still requires exact head equality.
    if authority_revision not in {revision, alembic_revision}:
        raise RuntimeError("dataset authority revision is not aligned with Alembic head")
