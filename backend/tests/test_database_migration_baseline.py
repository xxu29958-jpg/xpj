"""Empty-database init + schema migration version tracking + identity seed."""
from __future__ import annotations

from sqlalchemy import inspect, select, text

import app.database as database
from app.database import (
    BASELINE_MIGRATION_NAME,
    SessionLocal,
    engine,
    init_db,
)
from app.models import Expense, OcrFact
from tests._infra.migration_helpers import (
    expense_columns,
    indexes,
    reset_empty_database,
    table_columns,
    table_create_sql,
)

ALEMBIC_HEAD_REVISION = "20260603_0002"


def test_empty_database_initializes_schema_and_runtime_data() -> None:
    reset_empty_database()

    init_db()

    inspector = inspect(engine)
    assert "expenses" in inspector.get_table_names()
    assert "category_rules" in inspector.get_table_names()
    assert "duplicate_ignores" in inspector.get_table_names()
    assert "ledger_audit_logs" in inspector.get_table_names()
    assert "merchant_aliases" in inspector.get_table_names()
    assert "tags" in inspector.get_table_names()
    assert "expense_tags" in inspector.get_table_names()
    assert "expense_items" in inspector.get_table_names()
    assert "expense_splits" in inspector.get_table_names()
    assert "bill_split_invitations" in inspector.get_table_names()
    assert "csv_import_batches" in inspector.get_table_names()
    assert "csv_import_rows" in inspector.get_table_names()
    assert "recurring_items" in inspector.get_table_names()
    assert "budgets" in inspector.get_table_names()
    assert "budget_categories" in inspector.get_table_names()
    assert "goals" in inspector.get_table_names()
    assert "exchange_rates" in inspector.get_table_names()
    assert "fx_rates" in inspector.get_table_names()
    assert "dashboard_card_preferences" in inspector.get_table_names()
    assert "rule_application_batches" in inspector.get_table_names()
    assert "rule_application_changes" in inspector.get_table_names()
    assert "budget_advisor_audit_logs" in inspector.get_table_names()
    assert "schema_migrations" in inspector.get_table_names()
    assert "bootstrap_secret_consumptions" in inspector.get_table_names()
    assert {
        "tenant_id",
        "public_id",
        "thumbnail_path",
        "duplicate_status",
        "draft_idempotency_key",
        "original_currency_code",
        "original_amount_minor",
        "exchange_rate_to_cny",
        "exchange_rate_date",
        "exchange_rate_source",
        "image_perceptual_hash",
    }.issubset(expense_columns())
    assert "ix_ledger_audit_logs_ledger_created_at" in indexes("ledger_audit_logs")
    assert "ix_expenses_tenant_draft_idempotency_key" in indexes("expenses")
    assert "ix_expenses_tenant_status_merchant_expense_time" in indexes("expenses")
    assert "ix_expenses_tenant_status_merchant_confirmed_at" in indexes("expenses")
    assert "ix_merchant_aliases_tenant_alias_key" in indexes("merchant_aliases")
    assert "ix_merchant_aliases_tenant_canonical" in indexes("merchant_aliases")
    assert "ix_tags_tenant_key" in indexes("tags")
    assert "ix_expense_tags_tenant_expense" in indexes("expense_tags")
    assert "ix_expense_tags_tenant_tag" in indexes("expense_tags")
    assert "ix_expense_items_tenant_expense_position" in indexes("expense_items")
    assert "ix_expense_items_tenant_public_id" in indexes("expense_items")
    assert "ix_expense_items_tenant_category" in indexes("expense_items")
    assert "ix_expense_splits_tenant_expense_position" in indexes("expense_splits")
    assert "ix_expense_splits_tenant_public_id" in indexes("expense_splits")
    assert "ix_expense_splits_tenant_member" in indexes("expense_splits")
    assert "uq_bill_split_invitations_pending_receiver" in indexes(
        "bill_split_invitations"
    )
    assert "ix_csv_import_batches_tenant_public_id" in indexes("csv_import_batches")
    assert "ix_csv_import_batches_tenant_status_created_at" in indexes("csv_import_batches")
    assert "ix_csv_import_rows_tenant_batch_line" in indexes("csv_import_rows")
    assert "ix_csv_import_rows_tenant_batch_status" in indexes("csv_import_rows")
    assert "uq_csv_import_rows_tenant_expense_id" in indexes("csv_import_rows")
    assert "ix_recurring_items_tenant_status_next" in indexes("recurring_items")
    assert "ix_budgets_tenant_month" in indexes("budgets")
    assert "ix_budget_categories_tenant_month" in indexes("budget_categories")
    assert "ix_budget_categories_tenant_category" in indexes("budget_categories")
    assert "ix_goals_tenant_month_status" in indexes("goals")
    assert "ix_goals_tenant_category_month" in indexes("goals")
    assert "ix_goals_tenant_public_id" in indexes("goals")
    assert "ix_exchange_rates_tenant_currency_date" in indexes("exchange_rates")
    assert "ix_fx_rates_source_home_currency_date" in indexes("fx_rates")
    assert "ix_expenses_tenant_original_currency_date" in indexes("expenses")
    assert "ix_expenses_tenant_image_phash" in indexes("expenses")
    assert "ix_dashboard_cards_tenant_surface_position" in indexes(
        "dashboard_card_preferences"
    )
    assert "ix_dashboard_cards_tenant_surface_key" in indexes(
        "dashboard_card_preferences"
    )
    assert "ix_rule_application_batches_tenant_created_at" in indexes("rule_application_batches")
    assert "ix_rule_application_batches_tenant_status" in indexes("rule_application_batches")
    assert "uq_rule_application_batches_id_tenant_id" in indexes("rule_application_batches")
    assert "ix_rule_application_changes_tenant_batch" in indexes("rule_application_changes")
    assert "ix_rule_application_changes_tenant_expense" in indexes("rule_application_changes")
    rule_changes_sql = table_create_sql("rule_application_changes")
    assert "fk_rule_application_changes_batch_tenant" in rule_changes_sql
    assert "fk_rule_application_changes_expense_tenant" in rule_changes_sql
    assert {
        "amount_min_cents",
        "amount_max_cents",
        "source_contains",
        "tag_contains",
    }.issubset(table_columns("category_rules"))
    assert "ix_category_rules_tenant_enabled_priority" in indexes("category_rules")
    merchant_alias_sql = table_create_sql("merchant_aliases")
    assert "uq_merchant_aliases_tenant_alias_key" in merchant_alias_sql
    tags_sql = table_create_sql("tags")
    assert "uq_tags_tenant_key" in tags_sql
    assert "uq_tags_id_tenant_id" in tags_sql
    expense_tags_sql = table_create_sql("expense_tags")
    assert "fk_expense_tags_expense_tenant" in expense_tags_sql
    assert "fk_expense_tags_tag_tenant" in expense_tags_sql
    assert "uq_expense_tags_tenant_expense_tag" in expense_tags_sql
    duplicate_ignores_sql = table_create_sql("duplicate_ignores")
    assert "fk_duplicate_ignores_expense_tenant" in duplicate_ignores_sql
    assert "fk_duplicate_ignores_duplicate_tenant" in duplicate_ignores_sql
    assert "uq_duplicate_ignore_tenant_pair_kind" in duplicate_ignores_sql
    expenses_sql = table_create_sql("expenses")
    assert "uq_expenses_id_tenant_id" in expenses_sql
    assert "ck_expenses_amount_non_negative" in expenses_sql
    assert "ck_expenses_status_valid" in expenses_sql
    assert "ck_expenses_duplicate_status_valid" in expenses_sql
    assert "fk_expenses_duplicate_of_tenant" in expenses_sql
    expense_items_sql = table_create_sql("expense_items")
    assert "ck_expense_items_position_non_negative" in expense_items_sql
    # ADR-0035: amount_non_negative CHECK replaced by amount_by_kind + kind_valid
    assert "ck_expense_items_kind_valid" in expense_items_sql
    assert "ck_expense_items_amount_by_kind" in expense_items_sql
    assert "fk_expense_items_expense_tenant" in expense_items_sql
    assert "uq_expense_items_tenant_expense_position" in expense_items_sql
    expense_splits_sql = table_create_sql("expense_splits")
    assert "ck_expense_splits_position_non_negative" in expense_splits_sql
    assert "ck_expense_splits_amount_non_negative" in expense_splits_sql
    assert "fk_expense_splits_expense_tenant" in expense_splits_sql
    assert "fk_expense_splits_member_tenant" in expense_splits_sql
    assert "uq_expense_splits_tenant_expense_position" in expense_splits_sql
    assert "uq_expense_splits_tenant_expense_member" in expense_splits_sql
    csv_import_batches_sql = table_create_sql("csv_import_batches")
    assert "ck_csv_import_batches_status_valid" in csv_import_batches_sql
    assert "uq_csv_import_batches_id_tenant_id" in csv_import_batches_sql
    csv_import_rows_sql = table_create_sql("csv_import_rows")
    assert "ck_csv_import_rows_status_valid" in csv_import_rows_sql
    assert "fk_csv_import_rows_batch_tenant" in csv_import_rows_sql
    assert "fk_csv_import_rows_expense_tenant" in csv_import_rows_sql
    assert "uq_csv_import_rows_tenant_batch_line" in csv_import_rows_sql
    recurring_sql = table_create_sql("recurring_items")
    assert "ck_recurring_items_frequency_valid" in recurring_sql
    assert "ck_recurring_items_status_valid" in recurring_sql
    assert "fk_recurring_items_tenant_ledger" in recurring_sql
    category_rules_sql = table_create_sql("category_rules")
    assert "fk_category_rules_tenant_ledger" in category_rules_sql
    rule_application_batches_sql = table_create_sql("rule_application_batches")
    assert "fk_rule_application_batches_tenant_ledger" in rule_application_batches_sql
    merchant_aliases_sql = table_create_sql("merchant_aliases")
    assert "fk_merchant_aliases_tenant_ledger" in merchant_aliases_sql
    tags_sql = table_create_sql("tags")
    assert "fk_tags_tenant_ledger" in tags_sql
    budget_sql = table_create_sql("budgets")
    assert "ck_budgets_total_non_negative" in budget_sql
    assert "uq_budgets_tenant_month" in budget_sql
    assert "fk_budgets_tenant_ledger" in budget_sql
    budget_categories_sql = table_create_sql("budget_categories")
    assert "ck_budget_categories_amount_non_negative" in budget_categories_sql
    assert "uq_budget_categories_tenant_month_category" in budget_categories_sql
    assert "fk_budget_categories_budget_month" in budget_categories_sql
    goals_sql = table_create_sql("goals")
    assert "ck_goals_type_valid" in goals_sql
    assert "ck_goals_period_valid" in goals_sql
    assert "ck_goals_status_valid" in goals_sql
    assert "ck_goals_target_positive" in goals_sql
    assert "fk_goals_tenant_ledger" in goals_sql
    assert "uq_goals_active_total_scope" in indexes("goals")
    assert "uq_goals_active_category_scope" in indexes("goals")
    exchange_rates_sql = table_create_sql("exchange_rates")
    assert "uq_exchange_rates_tenant_currency_date" in exchange_rates_sql
    assert "ck_exchange_rates_rate_positive" in exchange_rates_sql
    assert "fk_exchange_rates_tenant_ledger" in exchange_rates_sql
    fx_rates_sql = table_create_sql("fx_rates")
    assert "uq_fx_rates_source_home_currency_date" in fx_rates_sql
    assert "ck_fx_rates_rate_positive" in fx_rates_sql
    dashboard_cards_sql = table_create_sql("dashboard_card_preferences")
    assert "ck_dashboard_cards_surface_valid" in dashboard_cards_sql
    assert "ck_dashboard_cards_position_non_negative" in dashboard_cards_sql
    assert "uq_dashboard_cards_tenant_surface_key" in dashboard_cards_sql
    assert "uq_dashboard_cards_tenant_surface_position" in dashboard_cards_sql
    assert "fk_dashboard_cards_tenant_ledger" in dashboard_cards_sql
    assert "fk_expenses_tenant_ledger" in table_create_sql("expenses")
    assert "fk_csv_import_batches_tenant_ledger" in table_create_sql("csv_import_batches")
    assert "retention_days" in table_columns("budget_advisor_audit_logs")
    auth_tokens_sql = table_create_sql("auth_tokens")
    assert "ck_auth_tokens_scope_valid" in auth_tokens_sql
    assert "uq_auth_tokens_active_principal" in indexes("auth_tokens")
    with engine.begin() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        owner_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'owner'")
        ).scalar_one()
        tester_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'tester_1'")
        ).scalar_one()
    assert owner_rules > 0
    assert tester_rules > 0
    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE name = :name"),
            {"name": BASELINE_MIGRATION_NAME},
        ).scalar_one()
    assert migration_count == 1
    with engine.begin() as connection:
        alembic_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert alembic_revision == ALEMBIC_HEAD_REVISION


def test_init_db_upgrades_pre_alembic_budget_advisor_audit_table() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        connection.execute(
            text(
                """
                CREATE TABLE budget_advisor_audit_logs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(64) NOT NULL,
                    actor_account_id INTEGER,
                    provider VARCHAR(64) NOT NULL,
                    model VARCHAR(120),
                    base_url VARCHAR(255),
                    month VARCHAR(7),
                    input_hash VARCHAR(64) NOT NULL,
                    success INTEGER DEFAULT '0' NOT NULL,
                    error_code VARCHAR(64),
                    suggestion_count INTEGER DEFAULT '0' NOT NULL,
                    duration_ms INTEGER,
                    called_at DATETIME NOT NULL
                )
                """
            )
        )

    init_db()

    assert "retention_days" in table_columns("budget_advisor_audit_logs")
    with engine.begin() as connection:
        alembic_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert alembic_revision == ALEMBIC_HEAD_REVISION


def test_init_db_runs_data_migrations_for_pre_alembic_existing_data() -> None:
    reset_empty_database()
    # Simulate a pre-Alembic user database that already has current ORM
    # tables from create_all() but no alembic_version row yet.
    from app import models  # noqa: F401

    database.Base.metadata.create_all(bind=engine)
    database.seed_identity_data()
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            source="pytest",
            raw_text="legacy receipt body",
            status="pending",
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    init_db()

    with SessionLocal() as db:
        facts = list(
            db.scalars(
                select(OcrFact).where(OcrFact.expense_id == expense_id)
            )
        )
    assert len(facts) == 1
    assert facts[0].ocr_provider == "legacy_expense_column"
    assert facts[0].raw_text == "legacy receipt body"
    with engine.begin() as connection:
        alembic_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert alembic_revision == ALEMBIC_HEAD_REVISION


def test_exchange_rates_seed_identity_ledger_ids() -> None:
    reset_empty_database()
    init_db()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            text(
                "INSERT INTO exchange_rates "
                "(tenant_id, public_id, currency_code, rate_date, rate_to_cny, source, created_at, updated_at) "
                "VALUES ('fx_only_ledger', 'fx-seed-public-id', 'JPY', '2026-05-01', 0.05000000, "
                "'manual', '2026-05-01 00:00:00', '2026-05-01 00:00:00')"
            )
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    database.seed_identity_data()

    with engine.begin() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM ledgers WHERE ledger_id = 'fx_only_ledger'")
        ).scalar_one()
    assert count == 1


def test_baseline_records_current_backend_version_for_restore_validation() -> None:
    from app.version import BACKEND_VERSION

    reset_empty_database()
    init_db()

    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT backend_version FROM schema_migrations WHERE name = :name"),
            {"name": BASELINE_MIGRATION_NAME},
        ).first()
    assert row is not None
    assert row[0] == BACKEND_VERSION


def test_record_schema_migration_persists_backend_version() -> None:
    reset_empty_database()
    init_db()

    database.record_schema_migration(
        "test-marker-with-version",
        backend_version="9.9.9-test",
        note="unit",
    )

    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT backend_version FROM schema_migrations "
                "WHERE name = 'test-marker-with-version'"
            )
        ).first()
    assert row is not None
    assert row[0] == "9.9.9-test"


def test_schema_migration_marker_query_is_safe_before_init() -> None:
    reset_empty_database()

    assert database.is_schema_migration_applied(BASELINE_MIGRATION_NAME) is False

    init_db()

    assert database.is_schema_migration_applied(BASELINE_MIGRATION_NAME) is True
    database.record_schema_migration(BASELINE_MIGRATION_NAME, note="repeat")
    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE name = :name"),
            {"name": BASELINE_MIGRATION_NAME},
        ).scalar_one()
    assert migration_count == 1
