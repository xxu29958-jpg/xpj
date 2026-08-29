"""Shared real-PostgreSQL probes for the money BIGINT migration tests."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, inspect, select, text

from app.database import SessionLocal, engine
from app.database._managed_postgres_migration_runtime import _prearmed_transaction
from app.models import (
    Account,
    BillSplitInvitation,
    Budget,
    ExpenseItem,
    ExpenseSplit,
    Ledger,
    LedgerMember,
    RecurringItem,
)
from app.money_contract import MONEY_COLUMNS_V1
from app.services.time_service import now_utc
from tests._infra.alembic_runtime import (
    reset_public_schema,
    run_alembic_for_test,
)

PREVIOUS_REVISION = "20260722_0001"
HEAD_REVISION = "20260729_0001"
LEGACY_INT32_MAX = 2_147_483_647
LEGACY_INT32_MIN = -2_147_483_648
LEGACY_CHECKS = {
    "ck_bill_split_invitations_amount_positive",
    "ck_budgets_total_non_negative",
    "ck_budgets_non_monthly_non_negative",
    "ck_budget_categories_amount_non_negative",
    "ck_goals_target_positive",
    "ck_debts_principal_positive",
    "ck_repayments_amount_positive",
    "ck_debt_forgivenesses_amount_positive",
    "ck_member_repayment_proposals_amount_positive",
    "ck_repayment_drafts_amount_positive",
    "ck_expense_items_amount_by_kind",
    "ck_expense_items_unit_price_non_negative",
    "ck_expense_splits_amount_non_negative",
    "ck_expenses_amount_non_negative",
    "ck_expenses_original_amount_non_negative",
    "ck_monthly_income_plans_amount_non_negative",
    "ck_csv_import_rows_amount_non_negative",
}


def alembic_config():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(backend_root / "migrations"),
    )
    return config


def run_alembic(action, *args) -> None:
    run_alembic_for_test(engine, alembic_config(), action, *args)


def load_migration():
    path = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / "20260729_0001_money_minor_bigint_expand.py"
    )
    spec = importlib.util.spec_from_file_location(
        "money_bigint_expand",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_migration(module) -> None:
    with engine.connect() as connection, _prearmed_transaction(
        connection,
        timeout_ms=20 * 60 * 1000,
        access_mode="read_write",
    ):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()


def reset_schema() -> None:
    reset_public_schema(engine)


def current_revision() -> str | None:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def column(table: str, column_name: str) -> dict:
    with engine.connect() as connection:
        columns = {item["name"]: item for item in inspect(connection).get_columns(table)}
    return columns[column_name]


def column_type(table: str, column_name: str) -> str:
    return str(column(table, column_name)["type"]).lower()


def constraint_state(
    table: str,
    name: str,
) -> tuple[str, bool, bool] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pg_get_expr(c.conbin, c.conrelid, true), "
                "c.convalidated, c.connoinherit FROM pg_constraint c "
                "WHERE c.conrelid = to_regclass(:table) "
                "AND c.contype = 'c' AND c.conname = :name"
            ),
            {"table": f"public.{table}", "name": name},
        ).one_or_none()
    return None if row is None else (str(row[0]), bool(row[1]), bool(row[2]))


def check_names(table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            str(row[0])
            for row in connection.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(:table) AND contype = 'c'"),
                {"table": f"public.{table}"},
            )
        }


def relfilenode(table: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(
                text("SELECT relfilenode FROM pg_class WHERE oid = CAST(:table AS regclass)"),
                {"table": f"public.{table}"},
            )
        )


def assert_head_shape() -> None:
    module = load_migration()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            expected = {
                (table, name): module._expected_expression(
                    connection,
                    table,
                    predicate,
                )
                for table, name, predicate in module._expected_checks()
            }
    for contract in MONEY_COLUMNS_V1:
        actual = column(contract.table, contract.column)
        actual_type = str(actual["type"]).lower()
        assert "bigint" in actual_type or actual_type == "int8"
        assert bool(actual["nullable"]) is contract.nullable
        for check in contract.checks:
            assert constraint_state(check.table, check.name) == (
                expected[(check.table, check.name)],
                True,
                False,
            )
    for table in {item.table for item in MONEY_COLUMNS_V1}:
        assert not (check_names(table) & LEGACY_CHECKS)


def seed_owner() -> tuple[int, int]:
    with SessionLocal() as db:
        existing = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        if existing is not None:
            member = db.scalar(
                select(LedgerMember).where(
                    LedgerMember.ledger_id == "owner",
                    LedgerMember.account_id == existing.owner_account_id,
                    LedgerMember.role == "owner",
                )
            )
            if member is None:
                raise AssertionError("C07 fixture owner ledger lacks its owner membership")
            return int(existing.owner_account_id), int(member.id)
        account = Account(display_name="boundary")
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id="owner",
            name="boundary ledger",
            owner_account_id=account.id,
        )
        db.add(ledger)
        db.flush()
        member = LedgerMember(
            ledger_id="owner",
            account_id=account.id,
            role="owner",
        )
        db.add(member)
        db.commit()
        return int(account.id), int(member.id)


def insert_legacy_expense(**values) -> int:
    """Insert against the reflected historical schema, not today's ORM shape."""

    now = now_utc()
    row = {
        "public_id": str(uuid4()),
        "category": "其他",
        "note": "",
        "source": "iPhone截图",
        "raw_text": "",
        "duplicate_status": "none",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        **values,
    }
    with engine.begin() as connection:
        expenses = Table("expenses", MetaData(), autoload_with=connection)
        return int(
            connection.scalar(
                expenses.insert().values(**row).returning(expenses.c.id)
            )
        )


def seed_legacy_csv_import_error_row() -> int:
    seed_owner()
    with engine.begin() as connection:
        batch_id = int(
            connection.scalar(
                text(
                    "INSERT INTO csv_import_batches ("
                    "public_id, tenant_id, file_name, status, total_rows, "
                    "valid_rows, error_rows, applied_rows, inserted_count, "
                    "created_at, updated_at"
                    ") VALUES ("
                    "'legacy-csv-batch', 'owner', 'legacy.csv', "
                    "'parsed_with_errors', 1, 0, 1, 0, 0, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                    ") RETURNING id"
                )
            )
        )
        return int(
            connection.scalar(
                text(
                    "INSERT INTO csv_import_rows ("
                    "tenant_id, batch_id, line_number, status, "
                    "error_code, error_message, amount_cents, "
                    "original_currency_code, original_amount_minor, "
                    "exchange_rate_to_cny, exchange_rate_source, merchant, "
                    "category, source, created_at, updated_at"
                    ") VALUES ("
                    "'owner', :batch_id, 2, 'error', 'legacy_error', "
                    "'legacy row', 450, 'CNY', 450, 1, 'base', "
                    "'Legacy row', '其他', 'CSV导入', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                    ") RETURNING id"
                ),
                {"batch_id": batch_id},
            )
        )


def seed_boundary_facts() -> None:
    seed_owner()
    expense_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=LEGACY_INT32_MAX,
        home_currency_code="CNY",
        original_currency_code="CNY",
        original_amount_minor=LEGACY_INT32_MAX,
        exchange_rate_to_cny=Decimal("1"),
        exchange_rate_source="base",
        fx_status="ready",
        merchant="boundary",
    )
    with SessionLocal() as db:
        db.add(
            ExpenseItem(
                tenant_id="owner",
                expense_id=expense_id,
                position=0,
                name="boundary discount",
                kind="discount",
                amount_cents=-1,
            )
        )
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key="boundary-merchant",
                merchant_name="boundary",
                baseline_amount_cents=LEGACY_INT32_MAX,
                last_amount_cents=LEGACY_INT32_MAX,
            )
        )
        db.add(
            Budget(
                tenant_id="owner",
                month="2026-07",
                total_amount_cents=0,
                non_monthly_amount_cents=0,
                rollover_amount_cents=LEGACY_INT32_MIN,
            )
        )
        db.commit()


def seed_legacy_zero_split() -> int:
    """Insert a split that the released pre-C07 API and CHECK accepted."""

    _account_id, member_id = seed_owner()
    expense_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=1_000,
        home_currency_code="CNY",
        original_currency_code="CNY",
        original_amount_minor=1_000,
        exchange_rate_to_cny=Decimal("1"),
        exchange_rate_source="base",
        fx_status="ready",
        merchant="legacy zero split",
    )
    with SessionLocal() as db:
        split = ExpenseSplit(
            tenant_id="owner",
            expense_id=expense_id,
            member_id=member_id,
            position=0,
            amount_cents=0,
        )
        db.add(split)
        db.commit()
        return int(split.id)


def seed_cross_currency_invitation() -> int:
    account_id, member_id = seed_owner()
    now = now_utc()
    expense_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=10_500,
        merchant="split-parent",
        home_currency_code="CNY",
        original_currency_code="USD",
        original_amount_minor=1_500,
        exchange_rate_to_cny=Decimal("7"),
        status="confirmed",
        expense_time=now,
        confirmed_at=now,
    )
    with SessionLocal() as db:
        invitation = BillSplitInvitation(
            sender_account_id=account_id,
            sender_ledger_id="owner",
            sender_member_id=member_id,
            sender_expense_id=expense_id,
            sender_display_name="A",
            receiver_account_id=account_id,
            receiver_display_name_snapshot="B",
            amount_cents=3_000,
            home_currency_code="CNY",
            original_currency_code="USD",
            original_amount_minor=1_500,
            exchange_rate_to_cny=Decimal("7"),
            exchange_rate_source="manual",
            status="invited",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            created_at=now_utc(),
        )
        db.add(invitation)
        db.commit()
        return int(invitation.id)


def seed_legacy_ocr_amount_fact() -> int:
    seed_owner()
    expense_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=None,
        home_currency_code="CNY",
        original_currency_code="CNY",
        original_amount_minor=None,
        exchange_rate_source=None,
        merchant="legacy OCR",
        status="pending",
    )
    with engine.begin() as connection:
        fact_id = connection.scalar(
            text(
                "INSERT INTO ocr_facts ("
                "public_id, tenant_id, expense_id, ocr_provider, "
                "raw_text, parsed_amount_cents, extracted_at, created_at, "
                "retention_days"
                ") VALUES ("
                "'legacy-ocr-c07', 'owner', :expense_id, 'mock', "
                "'legacy amount', 1000, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, 180"
                ") RETURNING id"
            ),
            {"expense_id": expense_id},
        )
    return int(fact_id)
