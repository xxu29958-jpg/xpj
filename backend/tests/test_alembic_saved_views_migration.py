"""The saved-query schema adds no financial facts and cannot discard saved intent."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.services.saved_view_service import create_view, resolve_view_query
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_saved_views_addition_preserves_original_bill_and_downgrade_refuses_saved_intent():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260927_0003")
        owner_id, _ = seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""INSERT INTO expenses (public_id, tenant_id, amount_cents,
                original_amount_minor, merchant, category, source, duplicate_status, status,
                image_path, created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'owner', 1000, 1000, '原账单', '其他', 'manual', 'none',
                'confirmed', 'owner/original.jpg', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 3)"""),
                {"id": str(uuid4())})
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM expenses")).mappings().one())
        run_alembic(command.upgrade, "20260928_0001")
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM expenses")).mappings().one()) == before
            assert db.scalar(text("SELECT count(*) FROM saved_views")) == 0
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == "20260928_0001"
        with SessionLocal() as db:
            saved = create_view(db, tenant_id="owner", actor_account_id=owner_id,
                idempotency_key=str(uuid4()), name="原月份", month_mode="fixed", month="2026-09",
                filter="", tag_public_id=None, home_currency_code="CNY")
        with pytest.raises(RuntimeError, match="cannot erase saved financial views"):
            run_alembic(command.downgrade, "20260927_0003")
        with SessionLocal() as db:
            assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                      public_id=saved.public_id)["month"] == "2026-09"
            assert dict(db.execute(text("SELECT * FROM expenses")).mappings().one()) == before
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == "20260928_0001"
    finally:
        reset_schema()
