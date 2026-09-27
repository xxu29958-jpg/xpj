"""Only actual captured definitions can become a period's original basis."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_migration_captures_current_definition_without_inventing_old_period_evidence():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260927_0002")
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            series_id = db.scalar(text("""INSERT INTO recurring_items (public_id, tenant_id, merchant_key,
                merchant_name, frequency, home_currency_code, baseline_amount_cents, last_amount_cents,
                occurrence_count, status, source, row_version, created_at, updated_at, archived_at)
                VALUES (:key, 'owner', 'original', '原观察定义', 'monthly', 'JPY', 1200, 1370,
                4, 'archived', 'candidate', 7, '2020-01-01T00:00:00Z', '2021-01-01T00:00:00Z',
                '2021-01-01T00:00:00Z') RETURNING id"""), {"key": str(uuid4())})
            db.execute(text("""INSERT INTO recurring_occurrences (tenant_id, series_id, period_start,
                row_version, updated_at) VALUES ('owner', :series, '2026-05-01', 3, '2021-01-01T00:00:00Z')"""),
                {"series": series_id})
        captured_after = datetime.now(UTC)
        run_alembic(command.upgrade, "20260927_0003")
        with engine.connect() as db:
            row = db.execute(text("SELECT * FROM recurring_item_revisions")).one()
            assert (row.series_id, row.row_version, row.change_kind, row.actor_account_id) == (series_id, 7, "baseline", None)
            assert row.recorded_at >= captured_after
            assert row.snapshot == {"merchant": "原观察定义", "merchant_key": "original", "frequency": "monthly",
                "home_currency_code": "JPY", "baseline_amount_cents": 1200, "next_expected_date": None,
                "status": "archived", "source": "candidate"}
            original = db.execute(text("SELECT * FROM recurring_items")).one()
            assert (original.last_amount_cents, original.occurrence_count, original.row_version) == (1370, 4, 7)
            assert original.updated_at == datetime(2021, 1, 1, tzinfo=UTC)
            occurrence = db.execute(text("SELECT * FROM recurring_occurrences")).one()
            assert (occurrence.row_version, occurrence.recorded_definition_row_version, occurrence.definition_recorded_at) == (3, None, None)
        with engine.begin() as db, pytest.raises(DBAPIError, match="recurring item revisions are immutable"):
            db.execute(text("UPDATE recurring_item_revisions SET snapshot = '{}'"))
        with engine.begin() as db, pytest.raises(DBAPIError, match="recorded recurring definitions are immutable"):
            db.execute(text("UPDATE recurring_occurrences SET recorded_definition_row_version = 7, definition_recorded_at = CURRENT_TIMESTAMP"))
        with engine.begin() as db, pytest.raises(DBAPIError, match="fk_recurring_item_revision_series_tenant"):
            db.execute(text("""INSERT INTO recurring_item_revisions (tenant_id, series_id, row_version,
                change_kind, snapshot, recorded_at) SELECT 'different-ledger', series_id, 8, 'edit',
                snapshot, CURRENT_TIMESTAMP FROM recurring_item_revisions"""))
        migration = import_module("migrations.versions.20260927_0003_recurring_definition_history")
        with engine.begin() as db:
            migration.assert_postcondition(db)
            db.execute(text("""INSERT INTO recurring_occurrences (tenant_id, series_id, period_start, row_version,
                updated_at, recorded_definition_row_version, definition_recorded_at)
                VALUES ('owner', :series, '2026-04-01', 1, CURRENT_TIMESTAMP, 7, CURRENT_TIMESTAMP)"""), {"series": series_id})
        with pytest.raises(RuntimeError, match="cannot erase recorded recurring definitions"):
            run_alembic(command.downgrade, "20260927_0002")
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == "20260927_0003"
            assert db.scalar(text("SELECT count(*) FROM recurring_item_revisions")) == 1
    finally:
        reset_schema()
