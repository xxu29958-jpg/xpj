"""The saved-query schema adds no financial facts and cannot discard saved intent."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.services.saved_view_service import create_view, resolve_view_query, update_view
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def _old_view(owner_id):
    public_id = str(uuid4())
    with SessionLocal.begin() as db:
        db.execute(text("""INSERT INTO saved_views (public_id, tenant_id, name, name_key,
            month_mode, month, filter, home_currency_code, created_by_account_id, created_at, updated_at)
            VALUES (:id, 'owner', '原月份', '原月份', 'fixed', '2026-09', '', 'CNY', :actor,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"id": public_id, "actor": owner_id})
    return public_id


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
        public_id = _old_view(owner_id)
        with pytest.raises(RuntimeError, match="cannot erase saved financial views"):
            run_alembic(command.downgrade, "20260927_0003")
        with SessionLocal() as db:
            assert db.scalar(text("SELECT month FROM saved_views WHERE public_id = :id"), {"id": public_id}) == "2026-09"
            assert dict(db.execute(text("SELECT * FROM expenses")).mappings().one()) == before
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == "20260928_0001"
    finally:
        reset_schema()


@pytest.mark.parametrize("operation", ["create", "update"])
def test_search_addition_preserves_old_queries_and_refuses_loss_of_new_conditions_or_receipts(operation):
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260930_0001")
        owner_id, _ = seed_owner()
        public_id = _old_view(owner_id)
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM saved_views")).mappings().one())
        run_alembic(command.upgrade, "20261008_0001")
        with engine.connect() as db:
            row = dict(db.execute(text("SELECT * FROM saved_views")).mappings().one())
            assert {key: row[key] for key in before} == before
            assert row["query_text"] == row["category"] == ""
        run_alembic(command.downgrade, "20260930_0001")
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM saved_views")).mappings().one()) == before
        run_alembic(command.upgrade, "20261008_0001")
        with SessionLocal() as db:
            assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                public_id=public_id)["month"] == "2026-09"
            save = create_view if operation == "create" else update_view
            changed = {} if operation == "create" else {"public_id": public_id, "expected_row_version": 1}
            saved = save(db, tenant_id="owner", actor_account_id=owner_id, **changed,
                idempotency_key=str(uuid4()), name="日用关键词", month_mode="fixed", month="2026-10",
                filter="", tag_public_id=None, home_currency_code="JPY", query_text="便利店", category="购物")
        with pytest.raises(RuntimeError, match="cannot erase saved search conditions"):
            run_alembic(command.downgrade, "20260930_0001")
        with SessionLocal.begin() as db:
            db.execute(text("DELETE FROM saved_views WHERE public_id = :id"), {"id": saved.public_id})
        with pytest.raises(RuntimeError, match="cannot erase saved search conditions"):
            run_alembic(command.downgrade, "20260930_0001")
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == "20261008_0001"
    finally:
        reset_schema()
