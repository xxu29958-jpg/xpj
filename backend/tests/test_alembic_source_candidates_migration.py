"""The shipped migration edge retains sources, ownership and downgrade protection."""
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models import Expense
from scripts.build_database_generation_program import compile_program
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.c07_money_protocol_probe import run_database_generation_upgrade
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_source_candidates_shipped_edge_preserves_expenses_and_refuses_evidence_erasure():
    parent, head = "20261029_0002", "20261101_0001"
    reset_schema()
    try:
        run_alembic(command.upgrade, parent)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            expense = Expense(tenant_id="owner", source="pytest", amount_cents=1000, original_amount_minor=1000,
                home_currency_code="CNY", original_currency_code="CNY", status="pending")
            db.add(expense)
            db.flush()
            expense_id = expense.id
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM expenses WHERE id=:id"), {"id": expense_id}).mappings().one())
        run_database_generation_upgrade(parent, head)
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM expenses WHERE id=:id"), {"id": expense_id}).mappings().one()) == before
            assert db.scalar(text("SELECT count(*) FROM expense_source_candidates")) == 0
        assert compile_program(Path(__file__).resolve().parents[1])["target_revision"] == head
        run_alembic(command.downgrade, parent)
        run_alembic(command.upgrade, head)
        with engine.begin() as db:
            db.execute(text("INSERT INTO expense_source_candidates (tenant_id,source_expense_id,expense_id,event_key,"
                "extraction_hash,event_index,evidence,created_at) VALUES ('owner',:id,:id,:key,:key,0,"
                "'{\"source_app\":\"alipay\"}',CURRENT_TIMESTAMP)"), {"id": expense_id, "key": "a" * 64})
        with pytest.raises(RuntimeError, match="cannot erase retained"):
            run_alembic(command.downgrade, parent)
        with engine.connect() as db:
            assert db.scalar(text("SELECT evidence->>'source_app' FROM expense_source_candidates")) == "alipay"
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == head
    finally:
        reset_schema()
