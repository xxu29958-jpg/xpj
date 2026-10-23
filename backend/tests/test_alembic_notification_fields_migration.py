"""The real upgrade preserves legacy capture bytes and blocks evidence-erasing downgrade."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def _snapshot():
    with engine.connect() as db:
        return dict(db.execute(text("SELECT * FROM payment_captures")).mappings().one())


def test_notification_fields_migration_keeps_original_and_refuses_erasure():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20261023_0001")
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""INSERT INTO payment_captures (public_id, tenant_id, actor_account_id, source,
                captured_at, original_currency, original_amount_minor, parser_version, candidates, kind,
                decisions, row_version, created_at) VALUES (:id, 'owner', (SELECT MIN(id) FROM accounts),
                'alipay', '2026-01-01T02:00:01Z', 'CNY', 2500, 'legacy', '[]', 'expense', '[]', 1, CURRENT_TIMESTAMP)"""),
                {"id": str(uuid4())})
        before = _snapshot()
        run_alembic(command.upgrade, "20261023_0002")
        after = _snapshot()
        assert after.pop("field_evidence") is None and after == before
        run_alembic(command.downgrade, "20261023_0001")
        assert _snapshot() == before
        run_alembic(command.upgrade, "20261023_0002")
        with SessionLocal.begin() as db:
            db.execute(text("UPDATE payment_captures SET field_evidence=:data"), {"data": '{"schema":"notification-fields/v1"}'})
        frozen = _snapshot()
        with pytest.raises(RuntimeError, match="notification field evidence exists"):
            run_alembic(command.downgrade, "20261023_0001")
        assert _snapshot() == frozen
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == "20261023_0002"
    finally:
        reset_schema()
