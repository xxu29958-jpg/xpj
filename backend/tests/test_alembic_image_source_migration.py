"""The real schema edge preserves old facts and refuses to erase source evidence."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.services.currency_binding_service import resolve_write_capability
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def _snapshot():
    with engine.connect() as db:
        return dict(db.execute(text("SELECT * FROM expenses")).mappings().one())


def test_image_source_migration_preserves_financial_bytes_and_blocks_evidence_erasure():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20261022_0001")
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""INSERT INTO expenses (public_id, tenant_id, merchant, category, source,
                amount_cents, original_amount_minor, original_currency_code, home_currency_code,
                duplicate_status, status, created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'owner', 'Old shop', '其他', 'manual', 1250, 1250, 'CNY', 'CNY',
                'none', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 3)"""), {"id": str(uuid4())})
        before = _snapshot()
        run_alembic(command.upgrade, "20261023_0001")
        after = _snapshot()
        assert after.pop("image_evidence") is None and after == before
        run_alembic(command.downgrade, "20261022_0001")
        assert _snapshot() == before
        run_alembic(command.upgrade, "20261023_0001")
        with SessionLocal.begin() as db:
            resolve_write_capability(db)
            db.execute(text("UPDATE expenses SET image_evidence=:data"), {"data": '{"schema":"image-source/v1"}'})
        frozen = _snapshot()
        with pytest.raises(RuntimeError, match="image source evidence exists"):
            run_alembic(command.downgrade, "20261022_0001")
        assert _snapshot() == frozen
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == "20261023_0001"
    finally:
        reset_schema()
