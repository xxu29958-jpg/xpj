"""The OCC metadata migration preserves both known and unadopted rate facts."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from app.services.currency_binding_service import resolve_write_capability
from app.services.identity_service import bootstrap_owner
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260909_0003"
_HEAD = "20260909_0004"


def test_rate_version_upgrade_preserves_the_exact_existing_fact_and_rejects_invalid_versions():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        public_id = str(uuid4())
        with SessionLocal() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""INSERT INTO exchange_rates (public_id, tenant_id, currency_code,
                home_currency_code, rate_date, rate_to_cny, source, created_at, updated_at)
                VALUES (:id, 'owner', 'USD', 'JPY', '2020-01-01', 150, 'manual',
                    '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"""), {"id": public_id})
            db.commit()
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM exchange_rates")).mappings().one())
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            after = dict(db.execute(text("SELECT * FROM exchange_rates")).mappings().one())
            assert after.pop("row_version") == 1
            assert after == before
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
        with SessionLocal() as db, pytest.raises(DBAPIError, match="row_version_positive"):
            resolve_write_capability(db)
            db.execute(text("UPDATE exchange_rates SET row_version = 0"))
        with SessionLocal() as db:
            resolve_write_capability(db)
            db.execute(text("UPDATE exchange_rates SET rate_to_cny = 151, row_version = 2"))
            db.commit()
        with pytest.raises(RuntimeError, match="cannot erase accepted manual rate versions"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unadopted_rate_gets_only_version_metadata_without_an_invented_currency():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            public_id = str(uuid4())
            db.execute(text("""INSERT INTO exchange_rates (public_id, tenant_id, currency_code,
                rate_date, rate_to_cny, source, created_at, updated_at)
                VALUES (:id, 'owner', 'USD', '2020-01-01', 150, 'manual',
                    '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"""), {"id": public_id})
            db.commit()
        run_alembic(command.upgrade, _PARENT)
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM exchange_rates")).mappings().one())
            assert before["home_currency_code"] is None
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            after = dict(db.execute(text("SELECT * FROM exchange_rates")).mappings().one())
            assert after.pop("row_version") == 1
            assert after == before
    finally:
        reset_schema()
