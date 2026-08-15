"""Shape and financial-fact round-trip tests for the C07 BIGINT migration."""

from __future__ import annotations

import re
import time
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.canonical_money_facts import canonical_money_facts_sha256
from app.database import SessionLocal, engine
from app.database._c07_production_contract import C07ProductionMigrationError
from app.database._c07_production_shape import (
    _ANALYZE_TABLE_SET_SHA256,
    _analyze_affected_tables,
    _assert_production_writer_fence,
)
from app.database._c07_transaction_timeout import c07_prearmed_transaction
from app.models import (
    BillSplitInvitation,
    Budget,
    CsvImportRow,
    Expense,
    ExpenseItem,
    ExpenseSplit,
    Goal,
    OcrFact,
)
from app.money_contract import MONEY_MINOR_MAX
from tests._infra.c07_money_migration import (
    HEAD_REVISION,
    PREVIOUS_REVISION,
    assert_head_shape,
    column_type,
    current_revision,
    reset_schema,
    run_alembic,
    run_alembic_without_c07_context,
    seed_boundary_facts,
    seed_cross_currency_invitation,
    seed_legacy_csv_import_error_row,
    seed_legacy_ocr_amount_fact,
    seed_legacy_zero_split,
    seed_owner,
)
from tests._infra.c07_money_protocol_probe import (
    run_database_generation_upgrade as _run_database_generation_upgrade,
)
from tests._infra.c07_money_runtime_checks import (
    assert_production_deadline_preserves_tighter_timeouts,
)
from tests._infra.c07_money_seed_pending_upload import (
    seed_legacy_pending_upload_money,
)

pytestmark = pytest.mark.real_db
LEGACY_INT32_MAX = 2_147_483_647
LEGACY_INT32_MIN = -2_147_483_648


def test_upgrade_previous_to_head_has_complete_shape() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    assert column_type("expenses", "amount_cents") in {"integer", "int4"}
    _run_database_generation_upgrade(PREVIOUS_REVISION, HEAD_REVISION)
    assert current_revision() == HEAD_REVISION
    assert_head_shape()


def test_fresh_upgrade_has_complete_shape() -> None:
    reset_schema()
    _run_database_generation_upgrade("base", HEAD_REVISION)
    assert current_revision() == HEAD_REVISION
    assert_head_shape()


def test_production_statistics_refresh_is_verified_and_replay_stable() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    _run_database_generation_upgrade(PREVIOUS_REVISION, HEAD_REVISION)

    with engine.begin() as connection:
        committed = _analyze_affected_tables(connection)
    with engine.begin() as connection:
        observed = _analyze_affected_tables(connection)

    expected = {
        "statistics_table_count": 18,
        "statistics_table_set_sha256": _ANALYZE_TABLE_SET_SHA256,
    }
    assert committed == expected
    assert observed == expected


def test_production_deadline_preserves_tighter_postgresql_timeouts() -> None:
    assert_production_deadline_preserves_tighter_timeouts()


def _idle_transaction_timeout_ms(connection) -> int:
    driver_connection = connection.connection.driver_connection
    original_autocommit = bool(driver_connection.autocommit)
    try:
        driver_connection.autocommit = True
        with driver_connection.cursor() as cursor:
            cursor.execute(
                "SELECT setting::bigint FROM pg_catalog.pg_settings "
                "WHERE name = 'transaction_timeout'"
            )
            return int(cursor.fetchone()[0])
    finally:
        driver_connection.autocommit = original_autocommit


def test_prearmed_transaction_restores_session_after_success() -> None:
    with engine.connect() as connection:
        previous_ms = _idle_transaction_timeout_ms(connection)
        with c07_prearmed_transaction(connection, timeout_ms=500):
            assert connection.scalar(
                text(
                    "SELECT setting::bigint FROM pg_catalog.pg_settings "
                    "WHERE name = 'transaction_timeout'"
                )
            ) == (500 if previous_ms == 0 else min(previous_ms, 500))

        assert not connection.invalidated
        assert _idle_transaction_timeout_ms(connection) == previous_ms


def test_prearmed_transaction_timeout_rolls_back_and_discards_connection() -> None:
    with engine.connect() as connection:
        previous_ms = _idle_transaction_timeout_ms(connection)

        with (
            pytest.raises(DBAPIError),
            c07_prearmed_transaction(connection, timeout_ms=500),
        ):
            assert connection.scalar(
                text(
                    "SELECT setting::bigint FROM pg_catalog.pg_settings "
                    "WHERE name = 'transaction_timeout'"
                )
            ) == (500 if previous_ms == 0 else min(previous_ms, 500))
            connection.execute(
                text(
                    "CREATE TABLE c07_prearmed_timeout_probe "
                    "(probe integer PRIMARY KEY)"
                )
            )
            connection.execute(text("SELECT pg_sleep(5)"))

        assert connection.invalidated

    with engine.connect() as replacement:
        assert _idle_transaction_timeout_ms(replacement) == previous_ms
        assert replacement.scalar(
            text("SELECT to_regclass(:table)"),
            {"table": "public.c07_prearmed_timeout_probe"},
        ) is None


def test_production_writer_fence_rejects_the_ordinary_test_database() -> None:
    with (
        engine.connect() as connection,
        pytest.raises(
            C07ProductionMigrationError,
            match="another client|PUBLIC CONNECT|unfenced login role",
        ),
    ):
        _assert_production_writer_fence(connection)


def test_exported_snapshot_survives_five_second_fence_timeout() -> None:
    exporter = engine.raw_connection()
    importer = None
    cleanup_elapsed = 0.0
    try:
        export_cursor = exporter.cursor()
        export_cursor.execute("SET statement_timeout = '5000ms'")
        export_cursor.execute(
            "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        export_cursor.execute("SELECT pg_export_snapshot()")
        snapshot_id = str(export_cursor.fetchone()[0])
        assert re.fullmatch(
            r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}",
            snapshot_id,
        )

        export_cursor.execute("SET statement_timeout = '0'")
        export_cursor.execute("SELECT pg_sleep(5.2)")

        importer = engine.raw_connection()
        import_cursor = importer.cursor()
        import_cursor.execute(
            "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        import_cursor.execute(  # noqa: S608
            f"SET TRANSACTION SNAPSHOT '{snapshot_id}'"
        )
        import_cursor.execute("SELECT 1")
        assert import_cursor.fetchone() == (1,)
    finally:
        cleanup_started = time.monotonic()
        if importer is not None:
            importer.rollback()
            importer.close()
        exporter.rollback()
        exporter.close()
        cleanup_elapsed = time.monotonic() - cleanup_started

    assert cleanup_elapsed < 2.0


def test_empty_existing_source_schema_cannot_impersonate_fresh_install() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    with pytest.raises(RuntimeError, match="requires the deployment ceremony"):
        run_alembic_without_c07_context(command.upgrade, HEAD_REVISION)
    assert current_revision() == PREVIOUS_REVISION
    assert column_type("expenses", "amount_cents") in {"integer", "int4"}


def test_upgrade_preserves_legacy_values_and_exposes_c07_release_bounds() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    seed_boundary_facts()
    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        budget = db.query(Budget).filter_by(month="2026-07").one()
        assert budget.rollover_amount_cents == LEGACY_INT32_MIN
        budget.rollover_amount_cents = LEGACY_INT32_MAX + 1
        db.commit()
        assert budget.rollover_amount_cents == LEGACY_INT32_MAX + 1
        budget.rollover_amount_cents = MONEY_MINOR_MAX
        db.commit()
        assert budget.rollover_amount_cents == MONEY_MINOR_MAX
        budget.rollover_amount_cents = MONEY_MINOR_MAX + 1
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        expense = db.query(Expense).filter_by(merchant="boundary").one()
        expense.amount_cents = -1
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        item = db.query(ExpenseItem).filter_by(
            name="boundary discount"
        ).one()
        item.kind = "product"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        item = db.query(ExpenseItem).filter_by(
            name="boundary discount"
        ).one()
        item.amount_cents = 1
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_goal_type_shape_rejects_null_truth_leaks_after_c07() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    seed_owner()
    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        spending = Goal(
            tenant_id="owner",
            name="spending shape",
            goal_type="spending_limit",
            period="monthly",
            month="2026-07",
            target_amount_cents=1,
        )
        debt = Goal(
            tenant_id="owner",
            name="debt shape",
            goal_type="debt_repayment",
            period="monthly",
            month=None,
            target_amount_cents=None,
        )
        db.add_all((spending, debt))
        db.commit()
        spending_id = spending.id
        debt_id = debt.id

        spending.target_amount_cents = None
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        spending = db.get(Goal, spending_id)
        assert spending is not None
        spending.month = None
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        debt = db.get(Goal, debt_id)
        assert debt is not None
        debt.month = "2026-07"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_existing_cross_currency_snapshot_is_not_reinterpreted() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    invitation_id = seed_cross_currency_invitation()
    run_alembic(command.upgrade, HEAD_REVISION)
    with SessionLocal() as db:
        invitation = db.get(BillSplitInvitation, invitation_id)
        assert invitation is not None
        assert invitation.amount_cents == 3_000
        assert invitation.original_currency_code == "USD"
        assert invitation.original_amount_minor == 1_500
        assert Decimal(invitation.exchange_rate_to_cny) == Decimal("7")
        assert invitation.exchange_rate_source == "manual"


def test_legacy_ocr_amount_fact_is_preserved_without_later_schema() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    fact_id = seed_legacy_ocr_amount_fact()
    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        fact = db.get(OcrFact, fact_id)
        assert fact is not None
        assert fact.parsed_amount_cents == 1000


def test_legacy_csv_import_row_is_preserved_without_later_schema() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    row_id = seed_legacy_csv_import_error_row()
    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        row = db.get(CsvImportRow, row_id)
        assert row is not None
        assert row.amount_cents == 450
        assert row.original_currency_code == "CNY"
        assert row.original_amount_minor == 450
        assert row.exchange_rate_to_cny == Decimal("1")
        assert row.exchange_rate_source == "base"
        assert row.status == "error"


def test_released_zero_split_survives_upgrade_without_fact_rewrite() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    split_id = seed_legacy_zero_split()
    with engine.connect() as connection:
        source_digest = canonical_money_facts_sha256(connection)

    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        split = db.get(ExpenseSplit, split_id)
        assert split is not None
        assert split.amount_cents == 0
    with engine.connect() as connection:
        assert canonical_money_facts_sha256(connection) == source_digest


def test_pending_upload_money_is_not_reinterpreted_without_provenance() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    pending_id, confirmed_id, foreign_id = seed_legacy_pending_upload_money()
    with engine.connect() as connection:
        source_digest = canonical_money_facts_sha256(
            connection,
        )
    run_alembic(command.upgrade, HEAD_REVISION)

    with SessionLocal() as db:
        pending = db.get(Expense, pending_id)
        assert pending is not None
        assert pending.amount_cents == 1_234
        assert pending.original_currency_code == "CNY"
        assert pending.original_amount_minor == 1_234
        assert pending.exchange_rate_to_cny == Decimal("1")
        assert pending.exchange_rate_date.isoformat() == "2026-07-20"
        assert pending.exchange_rate_source == "base"
        assert pending.merchant == "legacy pending upload"
        assert pending.category == "餐饮"
        assert pending.raw_text == "legacy text"
        assert pending.image_path == "uploads/legacy-pending.png"
        assert pending.row_version == 7
        assert pending.ocr_draft_fields == (
            '["original_amount", "original_currency", '
            '"exchange_rate_to_cny", "spent_at", "merchant"]'
        )

        confirmed = db.get(Expense, confirmed_id)
        assert confirmed is not None
        assert confirmed.amount_cents == 2_345
        assert confirmed.original_currency_code == "CNY"
        assert confirmed.original_amount_minor == 2_345

        foreign = db.get(Expense, foreign_id)
        assert foreign is not None
        assert foreign.amount_cents == 7_000
        assert foreign.original_currency_code == "USD"
        assert foreign.original_amount_minor == 1_000

    with engine.connect() as connection:
        assert canonical_money_facts_sha256(connection) == source_digest


def test_semantic_digest_binds_frozen_currency_fx_and_status_context() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    _pending_id, _confirmed_id, foreign_id = (
        seed_legacy_pending_upload_money()
    )
    row_id = seed_legacy_csv_import_error_row()
    invitation_id = seed_cross_currency_invitation()
    run_alembic(command.upgrade, HEAD_REVISION)

    with engine.connect() as connection, connection.begin():
        baseline = canonical_money_facts_sha256(connection)
        connection.execute(
            text(
                "UPDATE expenses SET original_currency_code = 'JPY' "
                "WHERE id = :id"
            ),
            {"id": foreign_id},
        )
        assert canonical_money_facts_sha256(connection) != baseline

    with engine.connect() as connection, connection.begin():
        baseline = canonical_money_facts_sha256(connection)
        connection.execute(
            text(
                "UPDATE expenses "
                "SET public_id = "
                "'11111111-1111-4111-8111-111111111111' "
                "WHERE id = :id"
            ),
            {"id": foreign_id},
        )
        assert canonical_money_facts_sha256(connection) != baseline

    with engine.connect() as connection, connection.begin():
        baseline = canonical_money_facts_sha256(connection)
        connection.execute(
            text(
                "UPDATE bill_split_invitations SET status = 'cancelled' "
                "WHERE id = :id"
            ),
            {"id": invitation_id},
        )
        assert canonical_money_facts_sha256(connection) != baseline

    with engine.connect() as connection, connection.begin():
        baseline = canonical_money_facts_sha256(connection)
        connection.execute(
            text(
                "UPDATE csv_import_rows "
                "SET exchange_rate_source = 'manual' "
                "WHERE id = :id"
            ),
            {"id": row_id},
        )
        assert canonical_money_facts_sha256(connection) != baseline
