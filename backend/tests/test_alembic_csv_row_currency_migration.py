"""Real PostgreSQL migration preserves staged money and adopts only unknown history."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from app.models import CsvImportBatch
from app.services.currency_adoption_service import adopt_currency_binding, adoption_preview
from app.services.currency_binding_service import resolve_write_capability
from app.services.identity_service import authenticate_session_token, bootstrap_owner
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260908_0001"
_HEAD = "20260908_0002"
_INSERT = """
    INSERT INTO csv_import_rows (tenant_id, batch_id, line_number, status, amount_cents,
        original_currency_code, original_amount_minor, merchant, category, source, created_at, updated_at)
    VALUES ('owner', :batch, :line, 'valid', 1200, :home, 1200, 'Train', '其他', 'CSV导入',
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id
"""


def _seed_row(db, home):
    batch = CsvImportBatch(tenant_id="owner", file_name="legacy.csv", total_rows=1, valid_rows=1)
    db.add(batch)
    db.flush()
    row_id = db.scalar(text(_INSERT), {"batch": batch.id, "line": 2, "home": home})
    db.commit()
    return batch.id, row_id


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_staged_rows_acquire_persisted_currency_and_cannot_be_relabelled(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            batch_id, row_id = _seed_row(db, home)
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            row = db.execute(text("SELECT id, home_currency_code, amount_cents, original_currency_code, original_amount_minor FROM csv_import_rows")).one()
            assert tuple(row) == (row_id, home, 1200, home, 1200)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="CSV row currency is immutable"):
            resolve_write_capability(db)
            db.execute(text("UPDATE csv_import_rows SET home_currency_code = 'EUR' WHERE id = :id"), {"id": row_id})
        with SessionLocal() as db, pytest.raises(DBAPIError, match="requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT), {"batch": batch_id, "line": 3, "home": home})
        with pytest.raises(RuntimeError, match="cannot erase captured CSV row currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unadopted_csv_row_waits_for_the_audited_owner_choice():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            _, row_id = _seed_row(db, "CNY")
        run_alembic(command.upgrade, _HEAD)
        with SessionLocal() as db:
            assert db.scalar(text("SELECT home_currency_code FROM csv_import_rows WHERE id = :id"), {"id": row_id}) is None
        # Adopt through the current runtime after checking the frozen CSV edge.
        run_alembic(command.upgrade, "head")
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            receipt = adopt_currency_binding(
                db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version,
                expected_state=preview.state, expected_revision=preview.binding_revision,
                expected_evidence_sha256=preview.evidence_sha256, reason="Owner verified the historical CSV amounts as CNY.",
            )
            assert receipt.home_currency_code == "CNY"
            row = db.execute(text("SELECT home_currency_code, amount_cents, original_currency_code, original_amount_minor FROM csv_import_rows WHERE id = :id"), {"id": row_id}).one()
            assert tuple(row) == ("CNY", 1200, "CNY", 1200)
    finally:
        reset_schema()
